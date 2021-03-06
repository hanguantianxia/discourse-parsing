# License: MIT

import ctypes as c
import socket
import logging
import re
import os
import xmlrpc.client

import nltk.data
from nltk.tree import ParentedTree

from discourseparsing.tree_util import (convert_parens_to_ptb_format,
                                        TREE_PRINT_MARGIN)
from discourseparsing.paragraph_splitting import ParagraphSplitter
from zpar import ZPar


class SyntaxParserWrapper():
    def __init__(self, zpar_model_directory=None, hostname=None,
                 port=None):
        self.zpar_model_directory = zpar_model_directory
        if self.zpar_model_directory is None:
            self.zpar_model_directory = os.getenv('ZPAR_MODEL_DIR',
                                                  'zpar/english')

        self.tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')
        self._zpar_proxy = None
        self._zpar_ref = None

        # if a port is specified, then we want to use the server
        if port:

            # if no hostname was specified, then try the local machine
            hostname = 'localhost' if not hostname else hostname
            logging.info('Trying to connect to zpar server at {}:{} ...'
                         .format(hostname, port))

            # try to see if a server actually exists
            connected, server_proxy = self._get_rpc(hostname, port)
            if connected:
                self._zpar_proxy = server_proxy
            else:
                logging.warning('Could not connect to zpar server')

        # otherwise, we want to use the python zpar module
        else:

            logging.info('Trying to locate zpar shared library ...')

            # get the path to the zpar shared library via the environment
            # variable
            zpar_library_dir = os.getenv('ZPAR_LIBRARY_DIR', '')
            zpar_library_path = os.path.join(zpar_library_dir, 'zpar.so')

            try:
                # Create a zpar wrapper data structure
                z = ZPar(self.zpar_model_directory)
                self._zpar_ref = z.get_parser()
            except OSError as e:
                logging.warning('Could not load zpar via python-zpar. ' +
                                'Did you set ZPAR_LIBRARY_DIR correctly?' + 
                                'Did you set ZPAR_MODEL_DIR correctly?')
                raise e


    @staticmethod
    def _get_rpc(hostname, port):
        '''
        Tries to get the zpar server proxy, if one exists.
        '''

        proxy = xmlrpc.client.ServerProxy(
            'http://{}:{}'.format(hostname, port),
            use_builtin_types=True, allow_none=True)
        # Call an empty method just to check that the server exists.
        try:
            proxy._()
        except xmlrpc.client.Fault:
            # The above call is expected to raise a Fault, so just pass here.
            pass
        except socket.error:
            # If no server was found, indicate so...
            return False, None

        # Otherwise, return that a server was found, and return its proxy.
        return True, proxy


    def tokenize_document(self, txt):
        tmpdoc = re.sub(r'\s+', r' ', txt.strip())
        sentences = [convert_parens_to_ptb_format(s)
                     for s in self.tokenizer.tokenize(tmpdoc)]
        return sentences

    def _parse_document_via_server(self, txt, doc_id):
        sentences = self.tokenize_document(txt)
        res = []
        for sentence in sentences:
            parsed_sent = self._zpar_proxy.parse_sentence(sentence)
            if parsed_sent:
                res.append(ParentedTree.fromstring(parsed_sent))
            else:
                logging.warning('The syntactic parser was unable to parse: ' +
                                '{}, doc_id = {}'.format(sentence, doc_id))
        logging.debug('syntax parsing results: {}'.format(
            [t.pformat(margin=TREE_PRINT_MARGIN) for t in res]))

        return res

    def _parse_document_via_lib(self, txt, doc_id):
        sentences = self.tokenize_document(txt)
        res = []
        for sentence in sentences:
            parsed_sent = self._zpar_ref.parse_sentence(sentence)
            if parsed_sent:
                res.append(
                    ParentedTree.fromstring(parsed_sent))
            else:
                logging.warning('The syntactic parser was unable to parse: ' +
                                '{}, doc_id = {}'.format(sentence, doc_id))
        logging.debug('syntax parsing results: {}'.format(
            [t.pformat(margin=TREE_PRINT_MARGIN) for t in res]))

        return res

    def parse_document(self, doc_dict):
        doc_id = doc_dict["doc_id"]
        logging.info('syntax parsing, doc_id = {}'.format(doc_id))

        # TODO should there be some extra preprocessing to deal with fancy
        # quotes, etc.? The tokenizer doesn't appear to handle it well
        paragraphs = ParagraphSplitter.find_paragraphs(doc_dict["raw_text"],
                                                       doc_id=doc_id)

        starts_paragraph_list = []
        trees = []
        no_parse_for_paragraph = False
        for paragraph in paragraphs:
            # try to use the server first
            if self._zpar_proxy:
                trees_p = self._parse_document_via_server(paragraph, doc_id)
            # then fall back to the shared library
            else:
                if self._zpar_ref is None:
                    raise RuntimeError('The ZPar server is unavailable.')
                trees_p = self._parse_document_via_lib(paragraph, doc_id)

            if len(trees_p) > 0:
                starts_paragraph_list.append(True)
                starts_paragraph_list.extend([False for t in trees_p[1:]])
                trees.extend(trees_p)
            else:
                # TODO add some sort of error flag to the dictionary for this
                # document?
                no_parse_for_paragraph = True

        logging.debug('starts_paragraph_list = {}, doc_id = {}'
                      .format(starts_paragraph_list, doc_id))

        # Check that either the number of True indicators in
        # starts_paragraph_list equals the number of paragraphs, or that the
        # syntax parser had to skip a paragraph entirely.
        assert (sum(starts_paragraph_list) == len(paragraphs)
                or no_parse_for_paragraph)
        assert len(trees) == len(starts_paragraph_list)

        return trees, starts_paragraph_list
