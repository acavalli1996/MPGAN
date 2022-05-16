import jetnet
from jetnet.datasets import JetNet
from jetnet import evaluation

import setup_training
from mpgan import augment, mask_manual
import plotting

import torch
from torch import Tensor
from torch.utils.data import DataLoader
from torch.autograd import Variable
from torch.autograd import grad as torch_grad
from torch.distributions.normal import Normal

import numpy as np

from os import remove

from tqdm import tqdm

import logging


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu" # Setting the usage of  GPU
    torch.autograd.set_detect_anomaly(False) # "False" chosed in order to avoid a severe memory leaks by setting "True"

    args = setup_training.init() # See code setup_training.py, creation of argparse object in which adding the arguments
    args.device = device
    logging.info("Args initalized")

    X_train = JetNet(  # See jetnet.py for the meaning of the arguments; Features, in order: ``[eta, phi, pt, mask]``.
        jet_type=args.jets, # jet_type (str): 'g' (gluon), 't' (top quarks), or 'q' (light quarks).
        train=True, # True for training, False for testing
        data_dir=args.datasets_path, # directory containing the datasets 
        num_particles=args.num_hits, # number of particoles to use (always <150, default = 30)
        use_mask=args.mask, # Defaults to true
        train_fraction=args.ttsplit, # Fraction of data to use as training
        num_pad_particles=args.pad_hits, # how many out of ``num_particles`` should be zero-padded. Def. to o
        noise_padding=args.noise_padding,
    )
    X_train_loaded = DataLoader(X_train, shuffle=True, batch_size=args.batch_size, pin_memory=True)
    # It reads, extracts and load data

    X_test = JetNet( # Same as X_train but with train = False
        jet_type=args.jets,
        train=False,
        data_dir=args.datasets_path,
        num_particles=args.num_hits,
        use_mask=args.mask,
        train_fraction=args.ttsplit,
        num_pad_particles=args.pad_hits,
        noise_padding=args.noise_padding,
    )
    X_test_loaded = DataLoader(X_test, batch_size=args.batch_size, pin_memory=True)
    logging.info("Data loaded")

    print(f"init {X_test.data.shape}")

    G, D = setup_training.models(args) # It initializes the arguments of G and D considering the chosed type of network (args.model)
    model_train_args, model_eval_args, extra_args = setup_training.get_model_args(args) 
    # Setup of specific model_args (=/args.model!!!) considering args.model
    logging.info("Models loaded")

    G_optimizer, D_optimizer = setup_training.optimizers(args, G, D)
    logging.info("Optimizers loaded")

    losses, best_epoch = setup_training.losses(args) 
    # Set up ``losses`` dict which stores model losses per epoch as well as evaluation metrics
    
    train( # Last function defined in this file
        args,# setup_training.init()
        X_train, # JetNet
        X_train_loaded, # Dataloader
        X_test, # JetNet
        X_test_loaded, # Dataloader
        G, # setup_training.models(args)
        D, # setup_training.models(args)
        G_optimizer, # setup_training.optimizers(args, G, D)
        D_optimizer, # setup_training.optimizers(args, G, D)
        losses, # setup_training.losses(args) 
        best_epoch, # setup_training.losses(args) 
        model_train_args, # setup_training.get_model_args(args) 
        model_eval_args, # setup_training.get_model_args(args) 
        extra_args, # setup_training.get_model_args(args) 
    )


def get_gen_noise(
    model_args,
    num_samples: int,
    num_particles: int,
    model: str = "mpgan", # note: MPGAN samples noise directly per particles
    device: str = None,
    noise_std: float = 0.2,
):
    """Gets noise needed for generator, arguments are defined in ``gen`` function below"""

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    dist = Normal(torch.tensor(0.0).to(device), torch.tensor(noise_std).to(device))
    point_noise = None

    if model == "mpgan" or model == "old_mpgan":
        if model_args["lfc"]: # 2 different strategis if MPGEN or MPLFCGEN
            noise = dist.sample((num_samples, model_args["lfc_latent_size"]))
        else:
            extra_noise_p = int("mask_learn_sep" in model_args and model_args["mask_learn_sep"])
            noise = dist.sample(
                (
                    num_samples,
                    num_particles + extra_noise_p,
                    model_args["latent_node_size"],
                )
            )
    elif model == "rgan" or model == "graphcnngan":
        noise = dist.sample((num_samples, model_args["latent_dim"]))
    elif model == "treegan":
        noise = [dist.sample((num_samples, 1, model_args["treegang_features"][0]))]
    elif model == "pcgan":
        noise = dist.sample((num_samples, model_args["pcgan_latent_dim"]))
        if model_args["sample_points"]:
            point_noise = Normal(torch.tensor(0.0).to(device), torch.tensor(1.0).to(device)).sample(
                [num_samples, num_particles, model_args["pcgan_z2_dim"]]
            )

    return noise, point_noise


def gen(
    model_args,
    G: torch.nn.Module,
    num_samples: int,
    num_particles: int,
    model: str = "mpgan",
    noise: Tensor = None,
    labels: Tensor = None,
    noise_std: float = 0.2,
    **extra_args,
) -> Tensor:
    """
    Generates ``num_samples`` jets in one go. Can optionally pass pre-specified ``noise``,
    else will randomly sample from a normal distribution.

    Needs an dict ``model_args`` containing the following model-specific args.

    mpgan:
    ``lfc`` (bool) use the latent fully connected layer (/ best football team in the world),
    ``lfc_latent_size`` (int) size of latent layer if ``lfc``,
    ``mask_learn_sep`` (bool) separate layer to learn masks,
    ``latent_node_size`` (int) size of each node's latent space, if not using lfc.

    rgan, graphcnngan:
    ``latent_dim`` (int)

    treegan:
    ``treegang_features`` (list)

    pcgan:
    ``pcgan_latent_dim`` (int),
    ``pcgan_z2_dim`` (int),
    ``sample_points`` (bool),
    ``G_pc`` (torch.nn.Module) if ``sample_points``


    Args:
        model_args: see above.
        G (torch.nn.Module): generator module.
        num_samples (int): # jets to generate.
        num_particles (int): # particles per jet.
        model (str): Choices listed in description. Defaults to "mpgan".
        noise (Tensor): Can optionally pass in your own noise. Defaults to None.
        labels (Tensor): Tensor of labels to condition on. Defaults to None.
        noise_std (float): Standard deviation of the Gaussian noise. Defaults to 0.2.
        **extra_args (type): extra args for generation

    Returns:
        Tensor: generated tensor of shape [num_samples, num_particles, num_features].

    """
    device = next(G.parameters()).device

    if labels is not None:
        assert labels.shape[0] == num_samples, "number of labels doesn't match num_samples"
        labels = labels.to(device)

    if noise is None:
        noise, point_noise = get_gen_noise(
            model_args, num_samples, num_particles, model, device, noise_std
        ) 
    # Generation of noise considering the chosen type of network 

    gen_data = G(noise, labels)

    if "mask_manual" in extra_args and extra_args["mask_manual"]:
        # TODO: add pt_cutoff to extra_args
        gen_data = mask_manual(model_args, gen_data, extra_args["pt_cutoff"])

    if model == "pcgan" and model_args["sample_points"]:
        gen_data = model_args["G_pc"](gen_data.unsqueeze(1), point_noise)

    logging.debug(gen_data[0, :10]) #[] it returns the elements up to the 10th of the first repetition (the one in position 0) 
    return gen_data


def optional_tqdm(iter_obj, use_tqdm, total=None, desc=None):
    if use_tqdm:
        return tqdm(iter_obj, total=total, desc=desc) # tqdm is a libraries, it outputs a progress bar around an iterable object
    else:
        return iter_obj


def gen_multi_batch(
    model_args,
    G: torch.nn.Module,
    batch_size: int,
    num_samples: int,
    num_particles: int,
    out_device: str = "cpu",
    detach: bool = False,
    use_tqdm: bool = True,
    model: str = "mpgan",
    noise: Tensor = None,
    labels: Tensor = None,
    noise_std: float = 0.2,
    **extra_args,
) -> Tensor:
    """
    Generates ``num_samples`` jets in batches of ``batch_size``.
    Args are defined in ``gen`` function
    """
    assert out_device == "cuda" or out_device == "cpu", "Invalid device type"

    if labels is not None:
        assert labels.shape[0] == num_samples, "number of labels doesn't match num_samples"

    gen_data = None
    
    # Another explanation of batch_norm 
    # https://towardsdatascience.com/batch-norm-explained-visually-how-it-works-and-why-neural-networks-need-it-b18919692739
    for i in optional_tqdm(
        range((num_samples // batch_size) + 1), use_tqdm, desc="Generating jets"
    ):
        num_samples_in_batch = min(batch_size, num_samples - (i * batch_size))

        if num_samples_in_batch > 0:
            gen_temp = gen( #It generates a tensor of shape [num_samples, num_particles, num_features].
                model_args, 
                G,
                num_samples=num_samples_in_batch,
                num_particles=num_particles,
                model=model,
                noise=noise,
                labels=None
                if labels is None
                else labels[(i * batch_size) : (i * batch_size) + num_samples_in_batch],
                noise_std=noise_std,
                **extra_args,
            )
            # It generates a gen_temp tensor of shape [num_samples, num_particles, num_features].
            
            if detach:
                gen_temp = gen_temp.detach() # The detached tensor is declared not to need a gradient.

            gen_temp = gen_temp.to(out_device)

        gen_data = gen_temp if i == 0 else torch.cat((gen_data, gen_temp), axis=0)
        # note: i == 0 is the firt iteration of the whole process, in the next iterations the new data are concatenated to the old

    return gen_data


# from https://github.com/EmilienDupont/wgan-gp
def gradient_penalty(gp_lambda, D, real_data, generated_data, batch_size, device, model="mpgan"):
    # Calculate interpolation
    alpha = (
        torch.rand(batch_size, 1, 1).to(device)
        if not model == "pcgan"
        else torch.rand(batch_size, 1).to(device)
    )
    alpha = alpha.expand_as(real_data) # note: expand_as expands the tensor at the same size of (passed_sensor)
    interpolated = alpha * real_data + (1 - alpha) * generated_data
    interpolated = Variable(interpolated, requires_grad=True).to(device)

    del alpha
    torch.cuda.empty_cache()

    # Calculate probability of interpolated examples
    prob_interpolated = D(interpolated)

    # Calculate gradients of probabilities with respect to examples
    gradients = torch_grad(
        outputs=prob_interpolated,
        inputs=interpolated,
        grad_outputs=torch.ones(prob_interpolated.size()).to(device),
        create_graph=True,
        retain_graph=True,
        allow_unused=True,
    )[0].to(device)
    gradients = gradients.contiguous()

    # Gradients have shape (batch_size, num_channels, img_width, img_height),
    # so flatten to easily take norm per example in batch
    gradients = gradients.view(batch_size, -1)

    # Derivatives of the gradient close to 0 can cause problems because of
    # the square root, so manually calculate norm and add epsilon
    gradients_norm = torch.sqrt(torch.sum(gradients ** 2, dim=1) + 1e-12)

    # Return gradient penalty
    gp = gp_lambda * ((gradients_norm - 1) ** 2).mean()
    return gp


bce = torch.nn.BCELoss()
mse = torch.nn.MSELoss()


def calc_D_loss(
    loss,
    D,
    data,
    gen_data,
    real_outputs,
    fake_outputs,
    run_batch_size,
    model="mpgan",
    gp_lambda=0,
    label_smoothing=False,
    label_noise=False,
):
    """
    calculates discriminator loss for the different possible loss functions
    + optionally applying label smoothing, label flipping, or a gradient penalty

    returns individual loss contributions as well for evaluation and plotting
    """
    device = data.device

    if loss == "og" or loss == "ls": # note: ls = least square loss function, used for MPGAN
        if label_smoothing:
            Y_real = torch.empty(run_batch_size).uniform_(0.7, 1.2).to(device)
            Y_fake = torch.empty(run_batch_size).uniform_(0.0, 0.3).to(device)
        else:
            Y_real = torch.ones(run_batch_size, 1).to(device)
            Y_fake = torch.zeros(run_batch_size, 1).to(device)

        # randomly flipping labels for D
        if label_noise:
            Y_real[torch.rand(run_batch_size) < label_noise] = 0
            Y_fake[torch.rand(run_batch_size) < label_noise] = 1
            
    # Loss defined considering the prediction and the ground truth taking into account the chosen loss 
    if loss == "og":
        D_real_loss = bce(real_outputs, Y_real)
        D_fake_loss = bce(fake_outputs, Y_fake)
    elif loss == "ls": # Least Square Loss function used for MPGAN
        D_real_loss = mse(real_outputs, Y_real)
        D_fake_loss = mse(fake_outputs, Y_fake)
    elif loss == "w": # Wasserstein loss function for PCGAN
        D_real_loss = -real_outputs.mean()
        D_fake_loss = fake_outputs.mean()
    elif loss == "hinge":
        D_real_loss = torch.nn.ReLU()(1.0 - real_outputs).mean()
        D_fake_loss = torch.nn.ReLU()(1.0 + fake_outputs).mean()

    D_loss = D_real_loss + D_fake_loss

    if gp_lambda:
        gp = gradient_penalty(gp_lambda, D, data, gen_data, run_batch_size, device, model) # It returns the gradient penalty
        gpitem = gp.item() # Returns the value of the tensor as a standard Python number. It only works for tensors with one element.
        D_loss += gp # Update of the D_loss
    else:
        gpitem = None

    return (
        D_loss,
        {
            "Dr": D_real_loss.item(),
            "Df": D_fake_loss.item(),
            "gp": gpitem,
            "D": D_real_loss.item() + D_fake_loss.item(),
        },
    )


def train_D(
    model_args,
    D,
    G,
    D_optimizer,
    G_optimizer,
    data,
    loss,
    loss_args={},
    gen_args={},
    augment_args=None,
    gen_data=None,
    labels=None,
    model="mpgan",
    epoch=0,
    print_output=False,
    **extra_args,
):
    logging.debug("Training D")
    log = logging.info if print_output else logging.debug

    D.train() # Training of the model (batchnorm, dropout, ecc.)
    D_optimizer.zero_grad() # It sets the gradient of the tensor to zero.
    G.eval()

    run_batch_size = data.shape[0]

    D_real_output = D(data.clone(), labels)
    log(f"D real output: \n {D_real_output[:10]}")

    if gen_data is None:
        gen_data = gen(
            model_args,
            G,
            num_samples=run_batch_size,
            model=model,
            labels=labels,
            **gen_args,
            **extra_args,
        )

    if augment_args is not None and augment_args.augment:
        p = augment_args.aug_prob if not augment_args.adaptive_prob else augment_args.augment_p[-1]
        data = augment.augment(augment_args, data, p)
        gen_data = augment.augment(augment_args, gen_data, p)

    log(f"G output: \n {gen_data[:2, :10]}")

    D_fake_output = D(gen_data, labels) # Passing the generated data of the generator to the Discriminator
    log(f"D fake output: \n {D_fake_output[:10]}")

    D_loss, D_loss_items = calc_D_loss( # Loss of D is calculated considering the output from real data and the output from fake data
        loss,
        D,
        data,
        gen_data,
        D_real_output,
        D_fake_output,
        run_batch_size,
        model=model,
        **loss_args,
    )
    D_loss.backward() # It computes the gradient in the backward pass in a neural network.
    D_optimizer.step() # The step method is implemented by the optimizer, it updates the parameters.
    return D_loss_items


def calc_G_loss(loss, fake_outputs):
    """Calculates generator loss for the different possible loss functions"""
    Y_real = torch.ones(fake_outputs.shape[0], 1, device=fake_outputs.device) # It returns a tensor filled with 1 of a certain size

    if loss == "og":
        G_loss = bce(fake_outputs, Y_real)
    elif loss == "ls": # Least Square
        G_loss = mse(fake_outputs, Y_real)
    elif loss == "w" or loss == "hinge":
        G_loss = -fake_outputs.mean()

    return G_loss


def train_G(
    model_args,
    D,
    G,
    G_optimizer,
    loss,
    batch_size,
    gen_args={},
    augment_args=None,
    labels=None,
    model="mpgan",
    epoch=0,
    **extra_args,
):
    logging.debug("gtrain")
    G.train() # Training of the model (batchnorm, dropout, ecc.)
    G_optimizer.zero_grad() 

    run_batch_size = labels.shape[0] if labels is not None else batch_size

    gen_data = gen(
        model_args,
        G,
        num_samples=run_batch_size,
        model=model,
        labels=labels,
        **gen_args,
        **extra_args,
    )

    if augment_args is not None and augment_args.augment:
        p = augment_args.aug_prob if not augment_args.adaptive_prob else augment_args.augment_p[-1]
        gen_data = augment.augment(augment_args, gen_data, p)

    D_fake_output = D(gen_data, labels) # Generated data used as input to the discriminator

    logging.debug("D fake output:")
    logging.debug(D_fake_output[:10])

    G_loss = calc_G_loss(loss, D_fake_output) #Loss of G calculated considering the output of D when using fake data (created by G)

    G_loss.backward() # Bacward step
    G_optimizer.step() # Optimization step.

    return G_loss.item()


def save_models(D, G, D_optimizer, G_optimizer, models_path, epoch, multi_gpu=False):
    if multi_gpu:
        torch.save(D.module.state_dict(), models_path + "/D_" + str(epoch) + ".pt") 
        torch.save(G.module.state_dict(), models_path + "/G_" + str(epoch) + ".pt")
    else:
        torch.save(D.state_dict(), models_path + "/D_" + str(epoch) + ".pt")
        torch.save(G.state_dict(), models_path + "/G_" + str(epoch) + ".pt")
        # torch.save saves an object (like D.state_dict()) to the disk (ex: models_path + "/D_" + str(epoch) + ".pt")
        # A state_dict is simply a Python dictionary object that maps each layer to its parameter tensor. 
        # For more details about it: https://pytorch.org/tutorials/beginner/saving_loading_models.html

    torch.save(D_optimizer.state_dict(), models_path + "/D_optim_" + str(epoch) + ".pt")
    torch.save(G_optimizer.state_dict(), models_path + "/G_optim_" + str(epoch) + ".pt")


def save_losses(losses, losses_path):
    for key in losses:
        np.savetxt(f"{losses_path}/{key}.txt", losses[key]) # note: it saves an array to a text file 


def evaluate(
    losses,
    real_jets,
    gen_jets,
    jet_type,
    num_particles=30,
    num_w1_eval_samples=10000,
    num_cov_mmd_eval_samples=100,
    num_fpnd_eval_samples=50000,
    fpnd_batch_size=16,
    efp_jobs=None,
):
    """Calculate evaluation metrics using the JetNet library and add them to the losses dict"""

    if "w1p" in losses:
        w1pm, w1pstd = evaluation.w1p(
            real_jets,
            gen_jets,
            exclude_zeros=True,
            num_eval_samples=num_w1_eval_samples,
            num_batches=real_jets.shape[0] // num_w1_eval_samples,
            average_over_features=False,
            return_std=True,
        )
        losses["w1p"].append(np.concatenate((w1pm, w1pstd)))

    if "w1m" in losses:
        print(real_jets.shape)
        print(gen_jets.shape)
        w1mm, w1mstd = evaluation.w1m(
            real_jets,
            gen_jets,
            num_eval_samples=num_w1_eval_samples,
            num_batches=real_jets.shape[0] // num_w1_eval_samples,
            return_std=True,
        )
        losses["w1m"].append(np.array([w1mm, w1mstd]))

    if "w1efp" in losses:
        w1efpm, w1efpstd = evaluation.w1efp(
            real_jets,
            gen_jets,
            use_particle_masses=False,
            num_eval_samples=num_w1_eval_samples,
            num_batches=real_jets.shape[0] // num_w1_eval_samples,
            average_over_efps=False,
            return_std=True,
            efp_jobs=efp_jobs,
        )
        losses["w1efp"].append(np.concatenate((w1efpm, w1efpstd)))

    if "fpnd" in losses:
        losses["fpnd"].append(
            evaluation.fpnd(
                gen_jets[:num_fpnd_eval_samples, :num_particles],
                jet_type,
                batch_size=fpnd_batch_size,
            )
        )

    if "coverage" in losses and "mmd" in losses:
        cov, mmd = evaluation.cov_mmd(real_jets, gen_jets, num_cov_mmd_eval_samples)
        losses["coverage"].append(cov)
        losses["mmd"].append(mmd)


def make_plots(
    losses,
    epoch,
    real_jets,
    gen_jets,
    real_mask,
    gen_mask,
    jet_type,
    num_particles,
    name,
    figs_path,
    losses_path,
    save_epochs=5,
    const_ylim=False,
    coords="polarrel",
    dataset="jetnet",
    loss="ls",
):
    """Plot histograms, jet images, loss curves, and evaluation curves"""
    real_masses = jetnet.utils.jet_features(real_jets)["mass"]
    gen_masses = jetnet.utils.jet_features(gen_jets)["mass"]

    if "w1efp" in losses:
        real_efps = jetnet.utils.efps(real_jets)
        gen_efps = jetnet.utils.efps(gen_jets)

        plotting.plot_part_feats( # note: Plot particle feature histograms
            jet_type,
            real_jets,
            gen_jets,
            real_mask,
            gen_mask,
            name=name + "p",
            figs_path=figs_path,
            losses=losses,
            num_particles=num_particles,
            coords=coords,
            dataset=dataset,
            const_ylim=const_ylim,
            show=False,
        )
        plotting.plot_jet_feats(
            jet_type,
            real_masses,
            gen_masses,
            real_efps,
            gen_efps,
            name=name + "j",
            figs_path=figs_path,
            losses=losses,
            show=False,
        )
    else:
        plotting.plot_part_feats_jet_mass(
            jet_type,
            real_jets,
            gen_jets,
            real_mask,
            gen_mask,
            real_masses,
            gen_masses,
            name=name + "pm",
            figs_path=figs_path,
            losses=losses,
            num_particles=num_particles,
            coords=coords,
            dataset=dataset,
            const_ylim=const_ylim,
            show=False,
        )

    if len(losses["G"]) > 1:
        plotting.plot_losses(losses, loss=loss, name=name, losses_path=losses_path, show=False) # # Fig. 8, Page 19, Kansal et al.

        try:
            remove(losses_path + "/" + str(epoch - save_epochs) + ".pdf")
        except:
            logging.info("Couldn't remove previous loss curves")

    if len(losses["w1p"]) > 1:
        plotting.plot_eval(
            losses,
            epoch,
            save_epochs,
            coords=coords,
            name=name + "_eval",
            losses_path=losses_path,
            show=False,
        )

        try:
            remove(losses_path + "/" + str(epoch - save_epochs) + "_eval.pdf")
        except:
            logging.info("Couldn't remove previous eval curves")


def eval_save_plot(
    args,
    X_test,
    D,
    G,
    D_optimizer,
    G_optimizer,
    model_args,
    losses,
    epoch,
    best_epoch,
    **extra_args,
):
    G.eval()  # It switch off some specific layer/parts of the model that behave differently during training and evaluation
    D.eval()  # Ex: dropout layers, batch norm layers, ...
    save_models(D, G, D_optimizer, G_optimizer, args.models_path, epoch, multi_gpu=args.multi_gpu)

    real_jets, real_mask = X_test.unnormalize_features( # Function from JETNET package
        X_test.data[: args.eval_tot_samples].clone(),
        ret_mask_separate=True,
        is_real_data=True,
        zero_mask_particles=True,
        zero_neg_pt=True,
    )
    """
    Unnormalized dataset of same type as input. Either a tensor/array of shape
            ``[num_jets, num_particles, num_features (including mask)]`` if ``ret_mask_separate``
            is False, else a tuple with a tensor/array of shape
            ``[num_jets, num_particles, num_features (excluding mask)]`` and another binary mask
            tensor/array of shape ``[num_jets, num_particles, 1]``
    """
    gen_output = gen_multi_batch(
        model_args,
        G,
        args.batch_size,
        args.eval_tot_samples,
        args.num_hits,
        out_device="cpu",
        model=args.model,
        detach=True,
        labels=X_test.jet_features[: args.eval_tot_samples]
        if (args.mask_c or args.clabels)
        else None,
        **extra_args,
    )
    gen_jets, gen_mask = X_test.unnormalize_features(
        gen_output,
        ret_mask_separate=True,
        is_real_data=False,
        zero_mask_particles=True,
        zero_neg_pt=True,
    )

    print(f"eval save plot {real_jets.shape} {gen_jets.shape}")
 
    real_jets = real_jets.detach().cpu().numpy() # The detached tensor is declared not to need a gradient.
    # Conversion of a pytorch cuda tensor to numpy array
    if real_mask is not None:
        real_mask = real_mask.detach().cpu().numpy()

    gen_jets = gen_jets.numpy()
    if gen_mask is not None:
        gen_mask = gen_mask.numpy()
        
    # For difference between pytorch tensor and numpy array see here: 
    # https://medium.com/@ashish.iitr2015/comparison-between-pytorch-tensor-and-numpy-array-de41e389c213

    evaluate( # Calculate evaluation metrics using the JetNet library and add them to the losses dict
        losses,
        real_jets,
        gen_jets,
        args.jets,
        num_particles=args.num_hits - args.pad_hits,
        num_w1_eval_samples=args.w1_num_samples[0],
        num_cov_mmd_eval_samples=args.cov_mmd_num_samples,
        fpnd_batch_size=args.fpnd_batch_size,
        efp_jobs=args.efp_jobs if hasattr(args, "efp_jobs") else None,
    )
    save_losses(losses, args.losses_path) # note: it saves an array to a text file 

    make_plots(
        losses,
        epoch,
        real_jets,
        gen_jets,
        real_mask,
        gen_mask,
        args.jets,
        args.num_hits,
        str(epoch),
        args.figs_path,
        args.losses_path,
        save_epochs=args.save_epochs,
        const_ylim=args.const_ylim,
        coords=args.coords,
        loss=args.loss,
    )

    # save model state and sample generated jets if this is the lowest w1m score yet
    if epoch > 0 and losses["w1m"][-1][0] < best_epoch[-1][1]:
        best_epoch.append([epoch, losses["w1m"][-1][0]])
        np.savetxt(f"{args.outs_path}/best_epoch.txt", np.array(best_epoch))

        np.save(f"{args.outs_path}/best_epoch_gen_jets", gen_jets)
        np.save(f"{args.outs_path}/best_epoch_gen_mask", gen_mask)

        with open(f"{args.outs_path}/best_epoch_losses.txt", "w") as f:
            f.write(str({key: losses[key][-1] for key in losses}))

        if args.multi_gpu:
            torch.save(G.module.state_dict(), f"{args.outs_path}/G_best_epoch.pt")
        else:
            torch.save(G.state_dict(), f"{args.outs_path}/G_best_epoch.pt")


def train_loop(
    args,
    X_train_loaded,
    epoch_loss,
    D,
    G,
    D_optimizer,
    G_optimizer,
    gen_args,
    D_losses,
    D_loss_args,
    model_train_args,
    epoch,
    extra_args,
):
    lenX = len(X_train_loaded)

    for batch_ndx, data in tqdm(
        enumerate(X_train_loaded), total=lenX, mininterval=0.1, desc=f"Epoch {epoch}"
    ):
        labels = data[1].to(args.device) if (args.clabels or args.mask_c) else None
        data = data[0].to(args.device)

        if args.model == "pcgan":
            # run through pre-trained inference network first i.e. find latent representation
            data = model_train_args["pcgan_G_inv"](data.clone())

        if args.num_critic > 1 or (batch_ndx == 0 or (batch_ndx - 1) % args.num_gen == 0): # Question: what is args.num_critic?
            # Maybe args.num_critic is used in order to train G before the training of D at the first iteration of the loop?
            D_loss_items = train_D( # Passing the generated data of the generator to the Discriminator in order to compute the losses
                model_train_args,
                D,
                G,
                D_optimizer,
                G_optimizer,
                data,
                loss=args.loss,
                loss_args=D_loss_args,
                gen_args=gen_args,
                augment_args=args,
                labels=labels,
                model=args.model,
                epoch=epoch - 1,
                print_output=(
                    batch_ndx == lenX - 1
                ),  # print outputs for the last iteration of each epoch
                **extra_args,
            )

            for key in D_losses:
                epoch_loss[key] += D_loss_items[key]

        if args.num_critic == 1 or (batch_ndx - 1) % args.num_critic == 0:
            epoch_loss["G"] += train_G( # #Loss of G calculated considering the output of D when using fake data (created by G)
                model_train_args,
                D,
                G,
                G_optimizer,
                loss=args.loss,
                batch_size=args.batch_size,
                gen_args=gen_args,
                augment_args=args,
                labels=labels,
                model=args.model,
                epoch=epoch - 1,
                **extra_args,
            )

        if args.bottleneck:
            if batch_ndx == 10:
                return

        if args.break_zero:
            if batch_ndx == 0:
                break


def train(
    args,
    X_train,
    X_train_loaded,
    X_test,
    X_test_loaded,
    G,
    D,
    G_optimizer,
    D_optimizer,
    losses,
    best_epoch,
    model_train_args,
    model_eval_args,
    extra_args,
):
    if args.start_epoch == 0 and args.save_zero: # Question: meaning of args.save_zero?
        eval_save_plot(
            args,
            X_test,
            D,
            G,
            D_optimizer,
            G_optimizer,
            model_eval_args,
            losses,
            0,
            best_epoch,
            **extra_args,
        )

    D_losses = ["Dr", "Df", "D"]
    if args.gp:
        D_losses.append("gp")

    epoch_loss = {"G": 0}
    for key in D_losses:
        epoch_loss[key] = 0

    gen_args = {"num_particles": args.num_hits, "noise_std": args.sd}
    D_loss_args = {
        "gp_lambda": args.gp,
        "label_smoothing": args.label_smoothing,
        "label_noise": args.label_noise,
    }
    lenX = len(X_train_loaded)  

    for i in range(args.start_epoch, args.num_epochs):
        epoch = i + 1
        logging.info(f"Epoch {epoch} starting")

        for key in epoch_loss: # Cleaning of epoch_loss for a new iteration of i 
            epoch_loss[key] = 0

        train_loop( # Function defined just above this one about the training
            args,
            X_train_loaded,
            epoch_loss,
            D,
            G,
            D_optimizer,
            G_optimizer,
            gen_args,
            D_losses,
            D_loss_args,
            model_train_args,
            epoch,
            extra_args,
        )
        logging.info(f"Epoch {epoch} Training Over")

        for key in D_losses:
            losses[key].append(epoch_loss[key] / (lenX / args.num_gen))
        losses["G"].append(epoch_loss["G"] / (lenX / args.num_critic))

        for key in epoch_loss:
            logging.info("{} loss: {:.3f}".format(key, losses[key][-1]))

        if (epoch) % args.save_epochs == 0:
            eval_save_plot(
                args,
                X_test,
                D,
                G,
                D_optimizer,
                G_optimizer,
                model_eval_args,
                losses,
                epoch,
                best_epoch,
                **extra_args,
            )
        elif (epoch) % args.save_model_epochs == 0:
            save_models(
                D, G, D_optimizer, G_optimizer, args.models_path, epoch, multi_gpu=args.multi_gpu
            )


if __name__ == "__main__":
    main()
