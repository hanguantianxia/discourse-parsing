#!/usr/bin/env python3
# License: MIT

import codecs
import logging
import json
import os

from discourseparsing.discourse_parsing import Parser
from discourseparsing.discourse_segmentation import (Segmenter,
                                                     extract_edus_tokens)
from discourseparsing.parse_util import SyntaxParserWrapper
from discourseparsing.tree_util import (TREE_PRINT_MARGIN,
                                        extract_preterminals,
                                        extract_converted_terminals)
from discourseparsing.io_util import read_text_file


def segment_and_parse(doc_dict, syntax_parser, segmenter, rst_parser):
    '''
    A method to perform syntax parsing, discourse segmentation, and RST parsing
    as necessary, given a partial document dictionary.
    See `convert_rst_discourse_tb.py` for details about document dictionaries.
    '''

    # Return empty lists if the input was blank.
    # (Check whether raw_text is available so this does not crash
    # when evaluating on pre-parsed treebank documents.)
    if 'raw_text' in doc_dict and not doc_dict['raw_text'].strip():
        # TODO add a unit test for this.
        logging.warning('The input contained no non-whitespace characters.' +
                        ' doc_id = {}'.format(doc_dict["doc_id"]))
        return [], []

    if 'syntax_trees' not in doc_dict:
        # Do syntactic parsing.
        trees, starts_paragraph_list = \
            syntax_parser.parse_document(doc_dict)
        doc_dict['syntax_trees'] = [t.pformat(margin=TREE_PRINT_MARGIN)
                                    for t in trees]
        preterminals = [extract_preterminals(t) for t in trees]
        doc_dict['token_tree_positions'] = [[x.treeposition() for x in
                                             preterminals_sentence]
                                            for preterminals_sentence
                                            in preterminals]
        doc_dict['tokens'] = [extract_converted_terminals(t) for t in trees]
        doc_dict['pos_tags'] = [[x.label() for x in preterminals_sentence]
                                for preterminals_sentence in preterminals]

    if 'edu_start_indices' not in doc_dict:
        # Do discourse segmentation.
        segmenter.segment_document(doc_dict)

        # Extract whether each EDU starts a paragraph.
        edu_starts_paragraph = []
        for tree_idx, tok_idx, _ in doc_dict['edu_start_indices']:
            val = (tok_idx == 0 and starts_paragraph_list[tree_idx])
            edu_starts_paragraph.append(val)
        assert len(edu_starts_paragraph) == len(doc_dict['edu_start_indices'])
        doc_dict['edu_starts_paragraph'] = edu_starts_paragraph

    # Extract a list of lists of (word, POS) tuples.
    edu_tokens = extract_edus_tokens(doc_dict['edu_start_indices'],
                                     doc_dict['tokens'])

    # Do RST parsing.
    rst_parse_trees = rst_parser.parse(doc_dict)

    return edu_tokens, rst_parse_trees


def main():
    import argparse
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('input_paths',
                        nargs='+',
                        help='A document to segment and parse.' +
                        ' Paragraphs should be separated by two or more' +
                        ' newline characters.')
    parser.add_argument('-g', '--segmentation_model',
                        help='Path to segmentation model.',
                        required=True)
    parser.add_argument('-p', '--parsing_model',
                        help='Path to RST parsing model.',
                        required=True)
    parser.add_argument('-a', '--max_acts',
                        help='Maximum number of actions for...?',
                        type=int, default=1)
    parser.add_argument('-n', '--n_best',
                        help='Number of parses to return', type=int, default=1)
    parser.add_argument('-s', '--max_states',
                        help='Maximum number of states to retain for \
                              best-first search',
                        type=int, default=1)
    parser.add_argument('-zp', '--zpar_port', type=int)
    parser.add_argument('-zh', '--zpar_hostname', default=None)
    parser.add_argument('-zm', '--zpar_model_directory', default=None)
    parser.add_argument('-v', '--verbose',
                        help='Print more status information. For every ' +
                        'additional time this flag is specified, ' +
                        'output gets more verbose.',
                        default=0, action='count')
    args = parser.parse_args()

    # Convert verbose flag to actually logging level.
    log_levels = [logging.WARNING, logging.INFO, logging.DEBUG]
    log_level = log_levels[min(args.verbose, 2)]
    # Make warnings from built-in warnings module get formatted more nicely.
    logging.captureWarnings(True)
    logging.basicConfig(format=('%(asctime)s - %(name)s - %(levelname)s - ' +
                                '%(message)s'), level=log_level)

    # Read the models.
    logging.info('Loading models')
    syntax_parser = \
        SyntaxParserWrapper(port=args.zpar_port, hostname=args.zpar_hostname,
                            zpar_model_directory=args.zpar_model_directory)
    segmenter = Segmenter(args.segmentation_model)

    parser = Parser(max_acts=args.max_acts,
                    max_states=args.max_states,
                    n_best=args.n_best)
    parser.load_model(args.parsing_model)

    for input_path in args.input_paths:
        logging.info('rst_parse input file: {}'.format(input_path))
        doc = read_text_file(input_path)

        logging.debug('rst_parse input. doc_id = {}, text = {}'
                      .format(input_path, doc))
        doc_dict = {"raw_text": doc, "doc_id": input_path}

        edu_tokens, complete_trees = segment_and_parse(doc_dict, syntax_parser,
                                                       segmenter, parser)

        complete_trees = [tree for tree in complete_trees]  # can't use a generator twice

        print(json.dumps({"edu_tokens": edu_tokens, \
            "scored_rst_trees": [{"score": tree["score"],
                                  "tree": tree["tree"]
                                          .pformat(margin=TREE_PRINT_MARGIN)}
                                 for tree in complete_trees]}))

        for i, tree in enumerate(complete_trees, 1):
            ptree_str = tree['tree'].__repr__() + '\n'
            with codecs.open(input_path + '_{}.parentedtree'.format(str(i)), 'w', 'utf-8') as ptree_file:
                ptree_file.write(ptree_str)


if __name__ == '__main__':
    main()
