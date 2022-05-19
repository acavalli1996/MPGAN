

import argparse # utility for Argument Parsing (module for argument/option analysis in the command line)
import sys

import os
from os import listdir
import pathlib

import torch
import torch.optim as optim

import numpy as np

from copy import deepcopy
import logging # Importing of the logging module (https://realpython.com/python-logging/) 
               # (https://docs.python.org/3/library/logging.html). 
               # It reports events that occur during normal operation of a program


# note: def setup_mpgan(args, gen) at rows 1050 (maybe something more due to previously comments)
        
def add_bool_arg(parser, name, help, default=False, no_name=None):
    # a parser is an object of type Argument Parser to which some arguments are associated
    
    varname = "_".join(name.split("-"))  # change hyphens to underscores
    # name.split("-") returns a list in which the words are not separated from themselves (alas there is a "-" in name so it happens       the opposite). 
    # join return a string from a list of  by joining all the elements of an iterable (list, string, tuple)
    group = parser.add_mutually_exclusive_group(required=False) # It creates a mutually exclusive group 
                                                                # function that ensure argparse to show on the command line
                                                                # only one of the argument in the mutually exclusive group
                                                                # (if false...?)
    group.add_argument("--" + name, dest=varname, action="store_true", help=help) 
    """ 
    dest = The name of the attribute to be added to the object returned by parse_args()
    action - The basic type of action to be taken when this argument is encountered at the command line
                 (store_true: stores the value True)
    """      
        
    if no_name is None:
        no_name = "no-" + name
        no_help = "don't " + help
    else:
        no_help = help
    group.add_argument("--" + no_name, dest=varname, action="store_false", help=no_help)
    parser.set_defaults(**{varname: default}) #(**kwargs): kwargs stands for keyword arguments
    # with **kwargs, the argument is not showed in a tuple but in a dictionary (alone wrt the tuple, in a new raw) 


class CustomFormatter(logging.Formatter):
    """Logging Formatter to add colors and count warning / errors"""

    grey = "\x1b[38;21m"
    green = "\x1b[1;32m"
    yellow = "\x1b[33;21m"
    red = "\x1b[31;21m"
    bold_red = "\x1b[31;1m"
    blue = "\x1b[1;34m"
    light_blue = "\x1b[1;36m"
    purple = "\x1b[1;35m"
    reset = "\x1b[0m"
    info_format = "%(asctime)s %(message)s"
    debug_format = "%(asctime)s [%(filename)s:%(lineno)d in %(funcName)s] %(message)s"

    def __init__(self, args):
        if args.log_file == "stdout":
            self.FORMATS = { # list of standard levels indicating the severity of events (increasing severity)
                logging.DEBUG: self.blue + self.debug_format + self.reset,
                logging.INFO: self.grey + self.info_format + self.reset,
                logging.WARNING: self.yellow + self.debug_format + self.reset,
                logging.ERROR: self.red + self.debug_format + self.reset,
                logging.CRITICAL: self.bold_red + self.debug_format + self.reset,
            }
        else:
            self.FORMATS = {
                logging.DEBUG: self.debug_format,
                logging.INFO: self.info_format,
                logging.WARNING: self.debug_format,
                logging.ERROR: self.debug_format,
                logging.CRITICAL: self.debug_format,
            }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno) # levelno is the numeric level of severity, levelname is the string of severity
        formatter = logging.Formatter(log_fmt, datefmt="%d/%m %H:%M:%S")
        return formatter.format(record)


class objectview(object):
    """converts a dict into an object"""

    def __init__(self, d):
        self.__dict__ = d


def parse_args():
    parser = argparse.ArgumentParser() 
    # Creation of the argparse object (parser) that will hold all the information necessary to parse the command line into Python           data types.
    
    ##########################################################
    # Meta
    ##########################################################

    parser.add_argument( # add_argument fills the ArgumentParser with information about program arguments. 
    # It tells the Argument Parser how to take the strings on the command line and turn them into objects.
        "--name",
        type=str,
        default="test",
        help="name or tag for model; will be appended with other info",
    )
    parser.add_argument(
        "--dataset", type=str, default="jets", help="dataset to use", choices=["jets", "jets-lagan"]
    )

    parser.add_argument("--ttsplit", type=float, default=0.7, help="ratio of train/test split")

    parser.add_argument( # Generator model
        "--model",
        type=str,
        default="mpgan",
        help="model to run",
        choices=["mpgan", "rgan", "graphcnngan", "treegan", "pcgan"],
    )
    parser.add_argument( # Discriminator model
        "--model-D",
        type=str,
        default="",
        help="model discriminator, mpgan default is mpgan, rgan. graphcnngan, treegan default is rgan, pcgan default is pcgan",
        choices=["mpgan", "rgan", "pointnet", "pcgan"],
    )

    add_bool_arg(parser, "load-model", "load a pretrained model", default=True) # Defined at the beginning of the code
    add_bool_arg(
        parser,
        "override-load-check",
        "override check for whether name has already been used",
        default=False,
    )
    add_bool_arg(
        parser,
        "override-args",
        "override original model args when loading with new args",
        default=False,
    )
    parser.add_argument(
        "--start-epoch",
        type=int,
        default=-1,
        help="which epoch to start training on, only applies if loading a model, by default start at the highest epoch model",
    )
    parser.add_argument("--num-epochs", type=int, default=2000, help="number of epochs to train")

    parser.add_argument("--dir-path", type=str, default="", help="path where output will be stored")
    parser.add_argument("--datasets-path", type=str, default="", help="path to datasets")

    parser.add_argument(
        "--num-samples", type=int, default=50000, help="num samples to evaluate every 5 epochs"
    )

    add_bool_arg(parser, "n", "run on nautilus cluster", default=False)
    add_bool_arg(parser, "bottleneck", "use torch.utils.bottleneck settings", default=False)
    add_bool_arg(parser, "lx", "run on lxplus", default=False)

    add_bool_arg(parser, "save-zero", "save the initial figure", default=False)
    add_bool_arg(parser, "no-save-zero-or", "override --n save-zero default", default=False)
    parser.add_argument(
        "--save-epochs", type=int, default=0, help="save outputs per how many epochs"
    )
    parser.add_argument(
        "--save-model-epochs", type=int, default=0, help="save models per how many epochs"
    )

    add_bool_arg(parser, "debug", "debug mode", default=False)
    add_bool_arg(parser, "break-zero", "break after 1 iteration", default=False)
    add_bool_arg(parser, "low-samples", "small number of samples for debugging", default=False)

    add_bool_arg(parser, "const-ylim", "const ylim in plots", default=False)

    parser.add_argument(
        "--jets",
        type=str,
        default="g",
        help="jet type",
        choices=["g", "t", "w", "z", "q", "sig", "bg"],
    )

    add_bool_arg(parser, "real-only", "use jets with ony real particles", default=False)

    add_bool_arg(parser, "multi-gpu", "use multiple gpus if possible", default=False)

    parser.add_argument(
        "--log-file", type=str, default="", help='path to log file ; "stdout" prints to console'
    )
    parser.add_argument(
        "--log",
        type=str,
        default="INFO",
        help="log level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )

    parser.add_argument("--seed", type=int, default=4, help="torch seed")

    ##########################################################
    # Architecture
    ##########################################################

    parser.add_argument("--num-hits", type=int, default=30, help="number of hits") # Question: number of particles in the jets?
    parser.add_argument(
        "--coords",
        type=str,
        default="polarrel",
        help="cartesian, polarrel or polarrelabspt",
        choices=["cartesian, polarrel, polarrelabspt"],
    )

    parser.add_argument(
        "--norm", type=float, default=1, help="normalizing max value of features to this value"
    )

    parser.add_argument("--sd", type=float, default=0.2, help="standard deviation of noise")

    parser.add_argument("--node-feat-size", type=int, default=3, help="node feature size")
    parser.add_argument(
        "--hidden-node-size",
        type=int,
        default=32, # Question: node feature size = 32, see D.2 Kansal et al.?
        help="hidden vector size of each node (incl node feature size)",
    )
    parser.add_argument(
        "--latent-node-size",
        type=int,
        default=0,
        help="latent vector size of each node - 0 means same as hidden node size",
    )

    parser.add_argument(
        "--clabels",
        type=int,
        default=0,
        help="0 - no clabels, 1 - clabels with pt only, 2 - clabels with pt and eta",
        choices=[0, 1, 2],
    )
    add_bool_arg(parser, "clabels-fl", "use conditional labels in first layer", default=True)
    add_bool_arg(parser, "clabels-hl", "use conditional labels in hidden layers", default=True)

    parser.add_argument( # Question: for PCGAN, see Kansal et al. D.4?
        "--fn", type=int, nargs="*", default=[256, 256], help="hidden fn layers e.g. 256 256" 
    )
    parser.add_argument(
        "--fe1g", # Generator edge feature layer 1
        type=int,
        nargs="*",
        default=0,
        help="hidden and output gen fe layers e.g. 64 128 in the first iteration - 0 means same as fe",
    )
    parser.add_argument(
        "--fe1d", # Discriminator edge featur layer 1
        type=int,
        nargs="*",
        default=0,
        help="hidden and output disc fe layers e.g. 64 128 in the first iteration - 0 means same as fe",
    )
    parser.add_argument(
        "--fe", 
        type=int,
        nargs="+",
        default=[96, 160, 192], # Nodes per layer in r-GAN (see Kansal et al., D.2)
        help="hidden and output fe layers e.g. 64 128",
    )
    parser.add_argument(
        "--fmg",
        type=int,
        nargs="*",
        default=[64],
        help="mask network layers e.g. 64; input 0 for no intermediate layers",
    )
    parser.add_argument(
        "--mp-iters-gen",
        type=int,
        default=0,
        help="number of message passing iterations in the generator",
    )
    parser.add_argument(
        "--mp-iters-disc",
        type=int,
        default=0,
        help="number of message passing iterations in the discriminator (if applicable)",
    )
    parser.add_argument(
        "--mp-iters",
        type=int,
        default=2,
        help="number of message passing iterations in gen and disc both - will be overwritten by gen or disc specific args if given",
    )
    add_bool_arg(parser, "sum", "mean or sum in models", default=True, no_name="mean")

    add_bool_arg(parser, "int-diffs", "use int diffs", default=False)
    add_bool_arg(parser, "pos-diffs", "use pos diffs", default=False)
    add_bool_arg(parser, "all-ef", "use all node features for edge distance", default=False)
    # add_bool_arg(parser, "scalar-diffs", "use scalar diff (as opposed to vector)", default=True) Commented by creator of the code.
    add_bool_arg(parser, "deltar", "use delta r as an edge feature", default=False)
    add_bool_arg(parser, "deltacoords", "use delta coords as edge features", default=False)

    parser.add_argument("--leaky-relu-alpha", type=float, default=0.2, help="leaky relu alpha")

    add_bool_arg(parser, "dea", "use early averaging discriminator", default=True)
    parser.add_argument(
        "--fnd", type=int, nargs="*", default=[], help="hidden disc output layers e.g. 128 64"
    )

    add_bool_arg(
        parser,
        "lfc",
        "use a fully connected network to go from noise vector to initial graph",
        default=False,
    )
    parser.add_argument(
        "--lfc-latent-size", type=int, default=128, help="size of lfc latent vector"
    )

    add_bool_arg(parser, "fully-connected", "use a fully connected graph", default=True)
    parser.add_argument(
        "--num-knn",
        type=int,
        default=10,
        help="# of nearest nodes to connect to (if not fully connected)",
    )
    add_bool_arg(
        parser,
        "self-loops",
        "use self loops in graph - always true for fully connected",
        default=True,
    )

    parser.add_argument(
        "--glorot", type=float, default=0, help="gain of glorot - if zero then glorot not used"
    )

    add_bool_arg(parser, "gtanh", "use tanh for g output", default=True)
    # add_bool_arg(parser, "dearlysigmoid", "use early sigmoid in d", default=False)

    ##########################################################
    # Masking
    ##########################################################

    add_bool_arg(parser, "mask-feat", "add mask as continuous fourth feature", default=False)
    add_bool_arg(parser, "mask-feat-bin", "add mask as binary fourth feature", default=False)
    add_bool_arg(parser, "mask-weights", "weight D nodes by mask", default=False)
    add_bool_arg(
        parser,
        "mask-manual",
        "manually mask generated nodes with pT less than cutoff",
        default=False,
    )
    add_bool_arg(
        parser,
        "mask-exp",
        "exponentially decaying or binary mask; relevant only if mask-manual is true",
        default=False,
    )
    add_bool_arg(parser, "mask-real-only", "only use masking for real jets", default=False)
    add_bool_arg(
        parser, "mask-learn", "learn mask from latent vars only use during gen", default=False
    )
    add_bool_arg(parser, "mask-learn-bin", "binary or continuous learnt mask", default=True)
    add_bool_arg(parser, "mask-learn-sep", "learn mask from separate noise vector", default=False)
    add_bool_arg(parser, "mask-disc-sep", "separate disc network for # particles", default=False)
    add_bool_arg(
        parser,
        "mask-fnd-np",
        "use num masked particles as an additional arg in D (dea will automatically be set true)",
        default=False,
    )
    add_bool_arg(parser, "mask-c", "conditional mask", default=True)
    add_bool_arg(
        parser, "mask-fne-np", "pass num particles as features into fn and fe", default=False
    )
    parser.add_argument(
        "--mask-epoch", type=int, default=0, help="# of epochs after which to start masking"
    )

    add_bool_arg(
        parser,
        "noise-padding",
        "use Gaussian noise instead of zero-padding for fake particles",
        default=False,
    )

    ##########################################################
    # Optimization
    ##########################################################

    parser.add_argument(
        "--optimizer",
        type=str,
        help="pick optimizer",
        choices=["adam", "rmsprop", "adadelta", "agcd"],
    )
    parser.add_argument(
        "--loss",
        type=str,
        default="ls",
        help="loss to use - options are og, ls, w, hinge",
        choices=["og", "ls", "w", "hinge"],
    )

    parser.add_argument(
        "--lr-disc",
        type=float,
        default=0,
        help="learning rate for discriminator; defaults are 3e-5, 6e-5, and 1.5e-5 for gluon, top, and quark jet resp.",
    )
    parser.add_argument(
        "--lr-gen",
        type=float,
        default=0,
        help="learning rate for generator; defaults are 1e-5, 2e-5, and 0.5e-5 for gluon, top, and quark jet resp.",
    )
    parser.add_argument("--beta1", type=float, default=0.9, help="Adam optimizer beta1")
    parser.add_argument("--beta2", type=float, default=0.999, help="Adam optimizer beta2")
    parser.add_argument("--batch-size", type=int, default=0, help="batch size")

    parser.add_argument(
        "--num-critic",
        type=int,
        default=1,
        help="number of critic updates for each generator update",
    )
    parser.add_argument(
        "--num-gen",
        type=int,
        default=1,
        help="number of generator updates for each critic update (num-critic must be 1 for this to apply)",
    )

    ##########################################################
    # Regularization
    ##########################################################

    add_bool_arg(parser, "batch-norm-disc", "use batch normalization", default=False)
    add_bool_arg(parser, "batch-norm-gen", "use batch normalization", default=False)
    add_bool_arg(
        parser, "spectral-norm-disc", "use spectral normalization in discriminator", default=False
    )
    add_bool_arg(
        parser, "spectral-norm-gen", "use spectral normalization in generator", default=False
    )

    parser.add_argument(
        "--disc-dropout", type=float, default=0.5, help="fraction of discriminator dropout"
    )
    parser.add_argument(
        "--gen-dropout", type=float, default=0, help="fraction of generator dropout"
    )

    add_bool_arg(parser, "label-smoothing", "use label smoothing with discriminator", default=False)
    parser.add_argument(
        "--label-noise", type=float, default=0, help="discriminator label noise (between 0 and 1)"
    )

    parser.add_argument(
        "--gp", type=float, default=0, help="WGAN generator penalty weight - 0 means not used"
    )

    ##########################################################
    # Augmentation
    ##########################################################

    # remember to add any new args to the if statement below
    add_bool_arg(parser, "aug-t", "augment with translations", default=False)
    add_bool_arg(parser, "aug-f", "augment with flips", default=False)
    add_bool_arg(parser, "aug-r90", "augment with 90 deg rotations", default=False)
    add_bool_arg(parser, "aug-s", "augment with scalings", default=False)
    parser.add_argument(
        "--translate-ratio", type=float, default=0.125, help="random translate ratio"
    )
    parser.add_argument(
        "--scale-sd", type=float, default=0.125, help="random scale lognormal standard deviation"
    )
    parser.add_argument(
        "--translate-pn-ratio", type=float, default=0.05, help="random translate per node ratio"
    )

    add_bool_arg(parser, "adaptive-prob", "adaptive augment probability", default=False)
    parser.add_argument(
        "--aug-prob", type=float, default=1.0, help="probability of being augmented"
    )

    ##########################################################
    # Evaluation
    ##########################################################

    add_bool_arg(parser, "fpnd", "calc fpnd", default=True)
    add_bool_arg(parser, "efp", "calc w1efp", default=True)
    # parser.add_argument("--fid-eval-size", type=int, default=8192, help="number of samples generated for evaluating fid")
    parser.add_argument(
        "--fpnd-batch-size",
        type=int,
        default=256,
        help="batch size when generating samples for fpnd eval",
    )
    parser.add_argument("--gpu-batch", type=int, default=50, help="")

    add_bool_arg(
        parser, "eval", "calculate the evaluation metrics: W1, FNPD, coverage, mmd", default=True
    )
    parser.add_argument(
        "--eval-tot-samples",
        type=int,
        default=50000,
        help="tot # of jets to generate to sample from",
    )

    parser.add_argument(
        "--w1-num-samples",
        type=int,
        nargs="+",
        default=[10000],
        help="array of # of jet samples to test",
    )

    parser.add_argument(
        "--cov-mmd-num-samples",
        type=int,
        default=100,
        help="size of samples to use for calculating coverage and MMD",
    )
    parser.add_argument(
        "--cov-mmd-num-batches",
        type=int,
        default=10,
        help="# of batches to average coverage and MMD over",
    )

    parser.add_argument(
        "--jf", type=str, nargs="*", default=["mass", "pt"], help="jet level features to evaluate"
    )

    ##########################################################
    # External models
    ##########################################################

    parser.add_argument("--latent-dim", type=int, default=128, help="")

    parser.add_argument(
        "--rgang-fc", type=int, nargs="+", default=[64, 128], help="rGAN generator layer node sizes"
    )
    parser.add_argument(
        "--rgand-sfc",
        type=int,
        nargs="*",
        default=0,
        help="rGAN discriminator convolutional layer node sizes",
    )
    parser.add_argument(
        "--rgand-fc", type=int, nargs="*", default=0, help="rGAN discriminator layer node sizes"
    )

    parser.add_argument(
        "--pointnetd-pointfc",
        type=int,
        nargs="*",
        default=[64, 128, 1024],
        help="pointnet discriminator point layer node sizes",
    )
    parser.add_argument(
        "--pointnetd-fc",
        type=int,
        nargs="*",
        default=[512],
        help="pointnet discriminator final layer node sizes",
    )

    parser.add_argument(
        "--graphcnng-layers",
        type=int,
        nargs="+",
        default=[32, 24],
        help="GraphCNN-GAN generator layer node sizes",
    )
    add_bool_arg(
        parser,
        "graphcnng-tanh",
        "use tanh activation for final graphcnn generator output",
        default=False,
    )

    parser.add_argument(
        "--treegang-degrees",
        type=int,
        nargs="+",
        default=[2, 2, 2, 2, 2],
        help="TreeGAN generator upsampling per layer",
    )
    parser.add_argument(
        "--treegang-features",
        type=int,
        nargs="+",
        default=[96, 64, 64, 64, 64, 3],
        help="TreeGAN generator features per node per layer",
    )
    parser.add_argument(
        "--treegang-support", type=int, default=10, help="Support value for TreeGCN loop term."
    )

    parser.add_argument(
        "--pcgan-latent-dim",
        type=int,
        default=128,
        help="Latent dim for object representation sampling",
    )
    parser.add_argument(
        "--pcgan-z1-dim",
        type=int,
        default=256,
        help="Object representation latent dim - has to be the same as the pre-trained point sampling network",
    )
    parser.add_argument(
        "--pcgan-z2-dim",
        type=int,
        default=10,
        help="Point latent dim - has to be the same as the pre-trained point sampling network",
    )
    parser.add_argument(
        "--pcgan-d-dim",
        type=int,
        default=256,
        help="PCGAN hidden dim - has to be the same as the pre-trained network",
    )
    parser.add_argument(
        "--pcgan-pool",
        type=str,
        default="max1",
        choices=["max", "max1", "mean"],
        help="PCGAN inference network pooling - has to be the same as the pre-trained network",
    )

    args = parser.parse_args()

    return args

    #### End parse_args() ####


def check_args_errors(args):
    if args.real_only and (not args.jets == "t" or not args.num_hits == 30):
        logging.error("real only arg works only with 30p jets - exiting")
        sys.exit()

    if args.int_diffs:
        logging.error("int_diffs not supported yet - exiting")
        sys.exit()

    if args.optimizer == "acgd" and (args.num_critic != 1 or args.num_gen != 1):
        logging.error("acgd can't have num critic or num gen > 1 - exiting")
        sys.exit()

    if args.n and args.lx:
        logging.error("can't be on nautilus and lxplus both - exiting")
        sys.exit()

    if args.latent_node_size and args.latent_node_size < 3:
        logging.error("latent node size can't be less than 2 - exiting")
        sys.exit()

    if args.all_ef and args.deltacoords:
        logging.error("all ef + delta coords not supported yet - exiting")
        sys.exit()

    if args.multi_gpu and args.loss != "ls":
        logging.warning("multi gpu not implemented for non-mse loss")
        args.multi_gpu = False


def process_args(args):
    check_args_errors(args)

    ##########################################################
    # Meta
    ##########################################################

    if args.debug:
        args.save_zero = True
        args.low_samples = True
        args.break_zero = True

    if torch.cuda.device_count() <= 1:
        args.multi_gpu = False

    if args.bottleneck:
        args.save_zero = False

    if args.n:
        if not (args.no_save_zero_or or args.num_hits == 100):
            args.save_zero = True
        args.efp_jobs = 1  # otherwise leads to a spike in memory usage on PRP
    else:
        args.efp_jobs = None

    if args.lx:
        if not args.no_save_zero_or:
            args.save_zero = True

    if args.save_epochs == 0:
        if args.num_hits <= 30:
            args.save_epochs = 5
        else:
            args.save_epochs = 1

    if args.save_model_epochs == 0:
        if args.num_hits <= 30:
            args.save_model_epochs = 5
        else:
            args.save_model_epochs = 1

    if args.low_samples:
        args.eval_tot_samples = 1000
        args.w1_num_samples = [100]
        args.num_samples = 1000

    if args.dataset == "jets-lagan" and args.jets == "g":
        args.jets = "sig"

    ##########################################################
    # Architecture
    ##########################################################
    
    # If not present specifics arg.mp_iters for both gen and disc, the args are equal to the one for the generic MPNet
    if not args.mp_iters_gen:
        args.mp_iters_gen = args.mp_iters
    if not args.mp_iters_disc:
        args.mp_iters_disc = args.mp_iters

    args.clabels_first_layer = args.clabels if args.clabels_fl else 0
    args.clabels_hidden_layers = args.clabels if args.clabels_hl else 0

    if args.latent_node_size == 0:
        args.latent_node_size = args.hidden_node_size

    ##########################################################
    # Masking
    ##########################################################

    if args.model == "mpgan" and (
        args.mask_feat
        or args.mask_manual
        or args.mask_learn
        or args.mask_real_only
        or args.mask_c
        or args.mask_learn_sep
    ):
        args.mask = True
    else:
        args.mask = False
        args.mask_c = False

    if args.dataset == "jets-lagan":
        args.mask_c = True

    if args.mask_fnd_np:
        logging.info("setting dea true due to mask-fnd-np arg")
        args.dea = True

    if args.noise_padding and not args.mask:
        logging.error("noise padding only works with masking - exiting")
        sys.exit()

    if args.mask_feat:
        args.node_feat_size += 1

    if args.mask_learn:
        if args.fmg == [0]:
            args.fmg = []

    ##########################################################
    # Optimization
    ##########################################################

    if args.batch_size == 0:
        if args.model == "mpgan" or args.model_D == "mpgan":
            if args.multi_gpu:
                if args.num_hits <= 30:
                    args.batch_size = 128
                else:
                    args.batch_size = 32
            else:
                if args.fully_connected:
                    if args.num_hits <= 30:
                        args.batch_size = 256
                    else:
                        args.batch_size = 32
                else:
                    if args.num_hits <= 30 or args.num_knn <= 10:
                        args.batch_size = 320
                    else:
                        if args.num_knn <= 20:
                            args.batch_size = 160
                        elif args.num_knn <= 30:
                            args.batch_size = 100
                        else:
                            args.batch_size = 32

    if args.lr_disc == 0:
        if args.jets == "g":
            args.lr_disc = 3e-5
        elif args.jets == "t":
            args.lr_disc = 6e-5
        elif args.jets == "q":
            args.lr_disc = 1.5e-5
    
    if args.lr_gen == 0:
        if args.jets == "g":
            args.lr_gen = 1e-5
        elif args.jets == "t":
            args.lr_gen = 2e-5
        elif args.jets == "q":
            args.lr_gen = 0.5e-5
    # note: the learning rate of the discriminator is three times greate with respect to the learning rate of the generator.
    
    if args.aug_t or args.aug_f or args.aug_r90 or args.aug_s:
        args.augment = True
    else:
        args.augment = False

    if args.augment:
        logging.warning("augmentation is very experimental - try at your own risk")

    ##########################################################
    # External models (see reference paper for the deatails of the architectures)
    ##########################################################

    if args.model_D == "":
        if args.model == "mpgan":
            args.model_D = "mpgan"
        elif args.model == "pcgan":
            args.model_D = "pcgan"
        else:
            args.model_D = "rgan"

    if args.model == "rgan":
        args.optimizer = "adam"
        args.beta1 = 0.5
        args.lr_disc = 0.0001
        args.lr_gen = 0.0001
        if args.model_D == "rgan":
            args.batch_size = 50
            args.num_epochs = 2000
        args.loss = "w"
        args.gp = 10 # WGAN generator penalty weight? It's the gradient penalty.
        args.num_critic = 5 # What is num_critic?

        if args.rgand_sfc == 0:
            args.rgand_sfc = [64, 128, 256, 256, 512]
        if args.rgand_fc == 0:
            args.rgand_fc = [128, 64]

        args.leaky_relu_alpha = 0.2

    if args.model == "graphcnngan":
        args.optimizer = "rmsprop"
        args.lr_disc = 0.0001
        args.lr_gen = 0.0001
        if args.model_D == "rgan":
            args.batch_size = 50
            args.num_epochs = 1000
            if args.rgand_sfc == 0:
                args.rgand_sfc = [64, 128, 256, 512]
            if args.rgand_fc == 0:
                args.rgand_fc = [128, 64]

        args.loss = "w"
        args.gp = 10 # WGAN generator penalty weight ?
        args.num_critic = 5

        args.leaky_relu_alpha = 0.2

        args.num_knn = 20

    args.pad_hits = 0
    if args.model == "treegan":
        # for treegan pad num hits to the next power of 2 (i.e. 30 -> 32)
        import math

        next_pow2 = 2 ** math.ceil(math.log2(args.num_hits))
        args.pad_hits = next_pow2 - args.num_hits
        args.num_hits = next_pow2

        args.optimizer = "adam"
        args.beta1 = 0
        args.beta2 = 0.99
        args.lr_disc = 0.0001
        args.lr_gen = 0.0001
        if args.model_D == "rgan":
            args.batch_size = 50
            args.num_epochs = 1000
            if args.rgand_sfc == 0:
                args.rgand_sfc = [64, 128, 256, 512]
            if args.rgand_fc == 0:
                args.rgand_fc = [128, 64]

        args.loss = "w"
        args.gp = 10 # WGAN generator penalty weight ? Gradient penalty?
        args.num_critic = 5

        args.leaky_relu_alpha = 0.2

    if args.model == "pcgan":
        args.optimizer = "adam"
        args.lr_disc = 0.0001
        args.lr_gen = 0.0001

        args.batch_size = 256
        args.loss = "w"
        args.gp = 10 # WGAN generator penalty weight ? Gradient penalty?
        args.num_critic = 5

        args.leaky_relu_alpha = 0.2

    if args.model_D == "rgan" and args.model == "mpgan":
        if args.rgand_sfc == 0:
            args.rgand_sfc = [64, 128, 256, 512]
        if args.rgand_fc == 0:
            args.rgand_fc = [128, 64]

    return args


def init_project_dirs(args):
    """
    Create 'datasets' and 'outputs' directories needed for the project.
    If not specified by the --datasets-path and --outputs-path args,
    defaults to creating them inside the working directory.
    """
    if args.datasets_path == "":
        if args.n:
            args.datasets_path = "/graphganvol/MPGAN/datasets/"
        else:
            args.datasets_path = str(pathlib.Path(__file__).parent.resolve()) + "/datasets/"

    os.system(f"mkdir -p {args.datasets_path}")

    if args.dir_path == "":
        if args.n:
            args.dir_path = "/graphganvol/MPGAN/outputs/"
        elif args.lx:
            args.dir_path = "/eos/user/r/rkansal/MPGAN/outputs/"
        else:
            args.dir_path = str(pathlib.Path(__file__).parent.resolve()) + "/outputs/"

    os.system(f"mkdir -p {args.dir_path}")

    return args


def init_model_dirs(args):
    """create directories for this training's logs, models, loss curves, and figures"""
    prev_models = [f[:-4] for f in listdir(args.dir_path)]  # removing .txt

    if args.name in prev_models:
        if args.name != "test" and not args.load_model and not args.override_load_check:
            raise RuntimeError(
                "A model directory of this name already exists, either change the name or use the --override-load-check flag"
            )

    os.system(f"mkdir -p {args.dir_path}/{args.name}")

    args_dict = vars(args)

    dirs = ["models", "losses", "figs"]

    for dir in dirs:
        args_dict[dir + "_path"] = f"{args.dir_path}/{args.name}/{dir}/"
        os.system(f'mkdir -p {args_dict[dir + "_path"]}')

    args_dict["args_path"] = f"{args.dir_path}/{args.name}/"
    args_dict["outs_path"] = f"{args.dir_path}/{args.name}/"

    args = objectview(args_dict)
    return args


def init_logging(args):
    """logging outputs to a file at ``args.log_file``;
    if ``args.log_file`` is stdout then it outputs to stdout"""
    if args.log_file == "stdout":
        handler = logging.StreamHandler(sys.stdout)
    else:
        if args.log_file == "":
            args.log_file = args.outs_path + args.name + "_log.txt"
        handler = logging.FileHandler(args.log_file)

    level = getattr(logging, args.log.upper())

    handler.setLevel(level)
    handler.setFormatter(CustomFormatter(args))

    #logging.basicConfig(handlers=[handler], level=level, force=True)
    logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)

    return args


def load_args(args):
    """Either save the arguments or, if loading a model, load the arguments for that model"""

    if args.load_model:
        if args.start_epoch == -1:
            # find the last saved model and start from there
            prev_models = [int(f[:-3].split("_")[-1]) for f in listdir(args.models_path)]

            if len(prev_models):
                args.start_epoch = max(prev_models)
            else:
                logging.debug("No model to load from")
                args.start_epoch = 0

        if args.start_epoch == 0:
            args.load_model = False
    else:
        args.start_epoch = 0

    if not args.load_model:
        # save args for posterity
        f = open(args.args_path + args.name + "_args.txt", "w+")
        f.write(str(vars(args)))
        f.close()
    elif not args.override_args:
        # load arguments from previous training
        temp = args.start_epoch, args.num_epochs  # don't load these

        f = open(args.args_path + args.name + "_args.txt", "r")
        args_dict = vars(args)
        load_args_dict = eval(f.read())
        for key in load_args_dict:
            args_dict[key] = load_args_dict[key]
        args = objectview(args_dict)
        f.close()

        args.load_model = True
        args.start_epoch, args.num_epochs = temp

    return args


def init(): 
    args = parse_args() # Defined at the beginning of the code
    if args.debug:
        args.log = "DEBUG"
        args.log_file = "stdout"
    args = init_project_dirs(args) # It creates 'datasets' and 'outputs' directories needed for the project.
    args = init_model_dirs(args) # It creates directories for this training's logs, models, loss curves, and figures
    args = init_logging(args) # It creates 
    args = process_args(args) 
    args = load_args(args) # Either save the arguments or, if loading a model, load the arguments for that model
    return args


def setup_mpgan(args, gen):
    """Setup MPGAN models"""
    from mpgan import MPGenerator, MPDiscriminator

    # args for LinearNet layers
    linear_args = {
        "leaky_relu_alpha": args.leaky_relu_alpha,
        "dropout_p": args.gen_dropout if gen else args.disc_dropout,
        "batch_norm": args.batch_norm_gen if gen else args.batch_norm_disc,
        "spectral_norm": args.spectral_norm_gen if gen else args.spectral_norm_disc,
    }

    # args for MPLayers
    mp_args = {
        "pos_diffs": args.pos_diffs,
        "all_ef": args.all_ef,
        "coords": args.coords,
        "delta_coords": args.deltacoords,
        "delta_r": args.deltar,
        "int_diffs": args.int_diffs,
        "clabels": args.clabels,
        "mask_fne_np": args.mask_fne_np,
        "fully_connected": args.fully_connected,
        "num_knn": args.num_knn,
        "self_loops": args.self_loops,
        "sum": args.sum,
    }
    # A dictionary is a mapping of key - parameter ("string" : parameter) 

    mp_args_first_layer_gen = {"clabels": args.clabels_first_layer}
    mp_args_first_layer_disc = {"clabels": args.clabels_first_layer, "all_ef": False}

    # args for MPNet common to generator and discriminator
    common_mpnet_args = {
        "num_particles": args.num_hits,
        "hidden_node_size": args.hidden_node_size,
        "fe_layers": args.fe,
        "fn_layers": args.fn,
        "fn1_layers": None,
    }

    # generator-specific args
    gen_args = {
        "mp_iters": args.mp_iters_gen,
        "fe1_layers": args.fe1g if args.fe1g else None,
        "final_activation": "tanh" if args.gtanh else "",
        "output_node_size": args.node_feat_size,
        "input_node_size": args.latent_node_size,
        "lfc": args.lfc,
        "lfc_latent_size": args.lfc_latent_size,
    }

    # discriminator-specific args
    disc_args = {
        "mp_iters": args.mp_iters_disc,
        "fe1_layers": args.fe1d if args.fe1d else None,
        "final_activation": "" if (args.loss == "w" or args.loss == "hinge") else "sigmoid",
        "input_node_size": args.node_feat_size,
        "dea": args.dea,
        "dea_sum": args.sum,
        "fnd": args.fnd,
        "mask_fnd_np": args.mask_fnd_np,
    }

    # args for masking
    mask_args = {
        "mask_feat": args.mask_feat,
        "mask_feat_bin": args.mask_feat_bin,
        "mask_weights": args.mask_weights,
        "mask_manual": args.mask_manual,
        "mask_exp": args.mask_exp,
        "mask_real_only": args.mask_real_only,
        "mask_learn": args.mask_learn,
        "mask_learn_bin": args.mask_learn_bin,
        "mask_learn_sep": args.mask_learn_sep, # (bool) separate layer to learn masks,
        "fmg": args.fmg,
        "mask_disc_sep": args.mask_disc_sep,
        "mask_fnd_np": args.mask_fnd_np,
        "mask_c": args.mask_c,
        "mask_fne_np": args.mask_fne_np,
    }

    if gen:
        return MPGenerator(
            **gen_args,
            **common_mpnet_args,
            mp_args=mp_args,
            mp_args_first_layer=mp_args_first_layer_gen,
            linear_args=linear_args,
            mask_args=mask_args,
        )
    else:
        return MPDiscriminator(
            **disc_args,
            **common_mpnet_args,
            mp_args=mp_args,
            mp_args_first_layer=mp_args_first_layer_disc,
            linear_args=linear_args,
            mask_args=mask_args,
        )


def models(args, gen_only=False):
    """Set up generator and discriminator models, either new or loaded from a state dict"""
    if args.model == "mpgan":
        G = setup_mpgan(args, gen=True)
        logging.info(G)
    elif args.model == "rgan":
        from ext_models import rGANG

        G = rGANG(args=deepcopy(args))
    elif args.model == "graphcnngan":
        from ext_models import GraphCNNGANG

        G = GraphCNNGANG(args=deepcopy(args))
    elif args.model == "treegan":
        from ext_models import TreeGANG

        G = TreeGANG(args.treegang_features, args.treegang_degrees, args.treegang_support)
        logging.info(G)
    elif args.model == "pcgan":
        from ext_models import latent_G

        G = latent_G(args.pcgan_latent_dim, args.pcgan_z1_dim)
    elif args.model == "old_mpgan":
        from mpgan import Graph_GAN

        G = Graph_GAN(gen=True, args=deepcopy(args))

    if gen_only:
        return G

    if args.model_D == "mpgan":
        D = setup_mpgan(args, gen=False)
        logging.info(D)
    elif args.model_D == "rgan":
        from ext_models import rGAND

        D = rGAND(args=deepcopy(args))
    elif args.model_D == "pointnet":
        from ext_models import PointNetMixD

        D = PointNetMixD(args=deepcopy(args))
    elif args.model_D == "pcgan":
        from ext_models import latent_D

        D = latent_D(args.pcgan_z1_dim)
    elif args.model_D == "old_mpgan":
        from mpgan import Graph_GAN

        G = Graph_GAN(gen=False, args=deepcopy(args))

    if args.load_model:
        try:
            G.load_state_dict( # Function that loads a model’s parameter dictionary using a deserialized state_dict
                torch.load(f"{args.models_path}/G_{args.start_epoch}.pt", map_location=args.device)
            ) # For more info about state_dict https://pytorch.org/tutorials/beginner/saving_loading_models.html#what-is-a-state-dict
            # A state_dict is simply a Python dictionary object that maps each layer to its parameter tensor. 
            D.load_state_dict(
                torch.load(f"{args.models_path}/D_{args.start_epoch}.pt", map_location=args.device)
            )
        except AttributeError:
            G = torch.load(f"{args.models_path}/G_{args.start_epoch}.pt", map_location=args.device)
            D = torch.load(f"{args.models_path}/D_{args.start_epoch}.pt", map_location=args.device)

    if args.multi_gpu:
        logging.info("Using", torch.cuda.device_count(), "GPUs")
        G = torch.nn.DataParallel(G)
        D = torch.nn.DataParallel(D)

    G = G.to(args.device) # Sending the model's parameter to the device.
    D = D.to(args.device)

    return G, D


def pcgan_models(args): 
    """Load pre-trained PCGAN models"""
    import ext_models
    from ext_models import G_inv_Tanh, G

    G_inv = G_inv_Tanh(args.node_feat_size, args.pcgan_d_dim, args.pcgan_z1_dim, args.pcgan_pool)
    G_pc = G(args.node_feat_size, args.pcgan_z1_dim, args.pcgan_z2_dim)

    pcgan_models_path = pathlib.Path(ext_models.__file__).parent.resolve() + "/pcgan_models/"
    G_inv.load_state_dict(
        torch.load(f"{pcgan_models_path}/pcgan_G_inv_{args.jets}.pt", map_location=args.device)
    )
    G_pc.load_state_dict(
        torch.load(f"{pcgan_models_path}/pcgan_G_pc_{args.jets}.pt", map_location=args.device)
    )

    if args.multi_gpu:
        logging.info("Using", torch.cuda.device_count(), "GPUs")
        G_inv = torch.nn.DataParallel(G_inv)
        G_pc = torch.nn.DataParallel(G_pc)

    G_inv = G_inv.to(args.device)
    G_pc = G_pc.to(args.device)

    G_inv.eval()
    G_pc.eval()

    return G_inv, G_pc


def get_model_args(args):
    """Set up model specific arguments for generation and training"""
    if args.model == "pcgan":
        G_inv, G_pc = pcgan_models(args) # Load pre-trained PCGAN models
        pcgan_train_args = {
            "sample_points": False,
            "G_inv": G_inv,
        }  # no need to sample points while training latent GAN
        pcgan_eval_args = {"sample_points": True, "G_pc": G_pc}
    else:
        pcgan_train_args = {}
        pcgan_eval_args = {}

    model_args = {}

    if args.model == "mpgan" or args.model == "old_mpgan":
        model_args = {
            "lfc": args.lfc,
            "lfc_latent_size": args.lfc_latent_size,
            "mask_learn_sep": args.mask_learn_sep,
            "latent_node_size": args.latent_node_size # It continues considering the if else structure! 
            if args.latent_node_size 
            else args.hidden_node_size, 
        }
    elif args.model == "rgan" or args.model == "graphcnngan":
        model_args = {"latent_dim": args.latent_dim}
    elif args.model == "treegan":
        model_args = {"treegang_features": args.treegang_features}
    elif args.model == "pcgan":
        model_args = {"pcgan_latent_dim": args.treegang_features, "pcgan_z2_dim": args.pcgan_z2_dim}

    model_train_args = {**model_args, **pcgan_train_args}
    model_eval_args = {**model_args, **pcgan_eval_args}
    # What is the purpose of these part of code if we are not taking into account PGAN? 

    extra_args = {"mask_manual": args.mask_manual, "pt_cutoff": 0}  # TODO: get right pT cutoff

    return model_train_args, model_eval_args, extra_args


def optimizers(args, G, D):
    # Extraction of paramaters to optimize considering the use of spectral norm for gen/disc
    if args.spectral_norm_gen:
        G_params = filter(lambda p: p.requires_grad, G.parameters())
        # note about filter function and lambda https://www.geeksforgeeks.org/lambda-filter-python-examples/
        # filter is a function that takes as input a function and a list of args (es: G.parameters()) that will be filtered when the           passed function is true. 
        # lambda is a generic name of an anonymous function, in this case it's true if gradient need to be computed 
    else:
        G_params = G.parameters()
        
    # Some info about spectral norm: https://openreview.net/pdf?id=B1QRgziT- ; 
    # https://pytorch.org/docs/stable/generated/torch.nn.utils.spectral_norm.html#torch.nn.utils.spectral_norm

    if args.spectral_norm_gen:
        D_params = filter(lambda p: p.requires_grad, D.parameters()) # Same as for generator
    else:
        D_params = D.parameters()
    
    # Optimization 
    if args.optimizer == "rmsprop": # For graphCNNgan. Question: Shuldn't be also of MPGAN?
        G_optimizer = optim.RMSprop(G_params, lr=args.lr_gen)
        D_optimizer = optim.RMSprop(D_params, lr=args.lr_disc)
    elif args.optimizer == "adadelta": # Question: no args.optimizer = "adadelta" defined in this code?
        G_optimizer = optim.Adadelta(G_params, lr=args.lr_gen)
        D_optimizer = optim.Adadelta(D_params, lr=args.lr_disc)
    elif args.optimizer == "adam" or args.optimizer == "None": # Adam optimizer for rGAN, TREEGAN, PCGAN 
        G_optimizer = optim.Adam(
            G_params, lr=args.lr_gen, weight_decay=5e-4, betas=(args.beta1, args.beta2)
        )
        D_optimizer = optim.Adam(
            D_params, lr=args.lr_disc, weight_decay=5e-4, betas=(args.beta1, args.beta2)
        )

    if args.load_model: # Question: argument not defined in the .init()?
        G_optimizer.load_state_dict(
            torch.load(
                args.models_path + "/G_optim_" + str(args.start_epoch) + ".pt", # Question: args.models_path not defined?
                map_location=args.device,
            )
        ) # A state_dict is simply a Python dictionary object that maps each layer to its parameter tensor.
        D_optimizer.load_state_dict(
            torch.load(
                args.models_path + "/D_optim_" + str(args.start_epoch) + ".pt",
                map_location=args.device,
            )
        )
        # .load_state_dict(state_dict) copies parameters from state_dict into che module that called the function + its descendant
        # Function that loads a model’s parameter dictionary using a deserialized state_dict
        # torch.load() loads an obect from a file (the object must be saved with torch.save() previously
 
    return G_optimizer, D_optimizer


def losses(args):
    """Set up ``losses`` dict which stores model losses per epoch as well as evaluation metrics"""
    losses = {}

    keys = ["D", "Dr", "Df", "G"] # Question: what is the meaning of the name of these key?
    # Maybe D (Discriminative loss) ??? , Discriminative real loss, Discriminative fake loss, Generative loss 
    if args.gp: # gp = WGAN generator penalty weight ? Gradient Penalty?
        keys.append("gp")

    eval_keys = ["w1p", "w1m", "w1efp", "fpnd", "coverage", "mmd"]

    if not args.fpnd:
        eval_keys.remove("fpnd")

    if not args.efp:
        eval_keys.remove("w1efp")

    keys = keys + eval_keys

    for key in keys:
        if args.load_model: # Question: not defined in init()?
            try:
                losses[key] = np.loadtxt(f"{args.losses_path}/{key}.txt")
                if losses[key].ndim == 1:
                    np.expand_dims(losses[key], 0)
                losses[key] = losses[key].tolist()
                if key in eval_keys:
                    losses[key] = losses[key][: int(args.start_epoch / args.save_epochs) + 1]
                else:
                    losses[key] = losses[key][: args.start_epoch + 1]
            except OSError:
                logging.info(f"{key} loss file not found")
                losses[key] = []
        else:
            losses[key] = []

    if args.load_model:
        try:
            best_epoch = np.loadtxt(f"{args.outs_path}/best_epoch.txt")
            if best_epoch.ndim == 1:
                np.expand_dims(best_epoch, 0)
            best_epoch = best_epoch.tolist()
        except OSError:
            logging.info("best epoch file not found")
            best_epoch = [[0, 10.0]]
    else:
        best_epoch = [[0, 10.0]]  # saves the best model [epoch, w1m score]

    return losses, best_epoch
