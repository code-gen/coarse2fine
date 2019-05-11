from __future__ import division

import argparse
import codecs
import glob
import os

import torch
from tqdm.auto import tqdm

import options
import table
import table.IO

arg_parser = argparse.ArgumentParser()
options.set_common_options(arg_parser)
options.set_model_options(arg_parser)
options.set_translation_options(arg_parser)
args = arg_parser.parse_args()

args.anno = os.path.join(args.root_dir, args.dataset, '{}.json'.format(args.split))

if args.cuda:
    torch.cuda.set_device(args.gpu_id[0])

if args.beam_size > 0:
    args.batch_size = 1


def dump_cfg(fp, cfg: dict) -> None:
    cfg = sorted(cfg.items(), key=lambda x: x[0])
    for k, v in cfg:
        fp.write("%32s: %s\n" % (k, v))


def dict_update(src: dict, new_data: dict):
    for k, v in new_data.items():
        src[k] = v
    return src


def main():
    js_list = table.IO.read_anno_json(args.anno)

    metric_name_list = ['tgt-token', 'lay-token', 'tgt', 'lay']

    prev_best = (None, None)

    for cur_model in glob.glob(args.model_path):
        args.model = cur_model
        print(" * evaluating model [%s]" % cur_model)

        checkpoint = torch.load(args.model, map_location=lambda storage, loc: storage)
        model_args = checkpoint['opt']

        fp = open("./experiments/%s/%s-eval.txt" % (model_args.exp_name, args.model.split("/")[-1]), "wt")

        # translator model
        translator = table.Translator(args, checkpoint)
        test_data = table.IO.OrderedIterator(
            dataset=table.IO.TableDataset(js_list, translator.fields, 0, None, False),
            device=args.gpu_id[0] if args.cuda else -1,  # -1 is CPU
            batch_size=args.batch_size,
            train=False, sort=True, sort_within_batch=False
        )

        r_list = []
        for batch in tqdm(test_data, desc="Inference"):
            r = translator.translate(batch)
            r_list += r

        r_list.sort(key=lambda x: x.idx)
        assert len(r_list) == len(js_list), 'len(r_list) != len(js_list): {} != {}'.format(len(r_list), len(js_list))

        for pred, gold in tqdm(zip(r_list, js_list), total=len(r_list), desc="Evaluation"):
            pred.eval(gold)

        for metric_name in tqdm(metric_name_list, desc="Dump results by metric"):

            if metric_name.endswith("-token"):
                c_correct = sum([len(set(x.get_by_name(metric_name)) - set(y[metric_name.split("-")[0]])) == 0 for x, y in zip(r_list, js_list)])
                acc = c_correct / len(r_list)

                out_str = 'result: {}: {} / {} = {:.2%}'.format(metric_name, c_correct, len(r_list), acc)
                fp.write(out_str + "\n")
                print(out_str)

            else:
                c_correct = sum((x.correct[metric_name] for x in r_list))
                acc = c_correct / len(r_list)

                out_str = 'result: {}: {} / {} = {:.2%}'.format(metric_name, c_correct, len(r_list), acc)
                fp.write(out_str + "\n")
                print(out_str)

                # dump incorrect examples
                for x in r_list:
                    for prd, tgt in x.incorrect[metric_name]:
                        fp.write("\tprd: %s\n\ttgt: %s\n\n" % (" ".join(prd), " ".join(tgt)))

            if metric_name == 'tgt' and (prev_best[0] is None or acc > prev_best[1]):
                prev_best = (cur_model, acc)
        # ---

        # save model args
        fp.write("\n\n")
        dump_cfg(fp, cfg=dict_update(args.__dict__, model_args.__dict__))
        fp.close()

    if (args.split == 'dev') and (prev_best[0] is not None):
        with codecs.open(os.path.join(args.root_dir, args.dataset, 'dev_best.txt'), 'w', encoding='utf-8') as f_out:
            f_out.write('{}\n'.format(prev_best[0]))


if __name__ == "__main__":
    main()
