import torch
import os
import torch.nn as nn
from torch.nn.functional import relu
import torch.optim as optim
from torch.optim import lr_scheduler
import torch.nn.functional as F
import torch.utils
from torchvision.transforms import v2 
from torchvision.utils import save_image
import numpy as np
from functools import reduce
from collections import defaultdict
import matplotlib.pyplot as plt
import random
import itertools
import time
import copy
from PIL import Image
from tifffile import imwrite
from model import UNet
import datasets.custom_dataset
from datasets.custom_dataset import get_dataloaders, CustomDataset
from data_utils import custom_collate_fn, BinningTransform, PatchTransform, MAPPING

    
def dice_loss(pred, target, smooth=1.):
    pred = pred.contiguous()
    target = target.contiguous()

    intersection = (pred * target).sum(dim=2).sum(dim=2)

    loss = (1 - ((2. * intersection + smooth) / (pred.sum(dim=2).sum(dim=2) + target.sum(dim=2).sum(dim=2) + smooth)))

    return loss.mean()


def calc_loss(pred, target, metrics, bce_weight=0.5):
    bce = F.binary_cross_entropy_with_logits(pred, target)

    pred = F.sigmoid(pred)
    dice = dice_loss(pred, target)

    loss = bce * bce_weight + dice * (1 - bce_weight)

    metrics['bce'] += bce.data.cpu().numpy() * target.size(0)
    metrics['dice'] += dice.data.cpu().numpy() * target.size(0)
    metrics['loss'] += loss.data.cpu().numpy() * target.size(0)

    return loss


def print_metrics(metrics, epoch_samples, phase):
    outputs = []
    for k in metrics.keys():
        outputs.append("{}: {:4f}".format(k, metrics[k] / epoch_samples))

    print("{}: {}".format(phase, ", ".join(outputs)))


def train_model(model, optimizer, scheduler, num_epochs):
    dataloaders = get_dataloaders()
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    
    best_model_wts = copy.deepcopy(model.state_dict())
    best_loss = 1e10

    for epoch in range(num_epochs):
        print('Epoch {}/{}'.format(epoch, num_epochs - 1))
        print('-' * 10)

        since = time.time()


        for phase in ['train', 'val']:

            metrics = defaultdict(float)
            epoch_samples = 0

            for inputs, labels in dataloaders[phase]:
                inputs = inputs.to(device)
                labels = labels.to(device)

                optimizer.zero_grad()

                with torch.set_grad_enabled(phase == 'train'):
                    outputs = model(inputs)
                    loss = calc_loss(outputs, labels, metrics)

                    if phase == 'train':
                        loss.backward()
                        optimizer.step()

                epoch_samples += inputs.size(0)
                
            if phase == 'train':
                scheduler.step()
                for param_group in optimizer.param_groups:
                    print("LR", param_group['lr'])

                model.train()
            else:
                model.eval()

            # # Nur einen Batch pro Epoche verwenden
            # for i, (inputs, labels) in enumerate(dataloaders[phase]):
            #     if i > 0:
            #         break
            #     inputs = inputs.to(device)
            #     labels = labels.to(device)

            #     optimizer.zero_grad()

            #     with torch.set_grad_enabled(phase == 'train'):
            #         outputs = model(inputs)
            #         loss = calc_loss(outputs, labels, metrics)

            #         if phase == 'train':
            #             loss.backward()
            #             optimizer.step()

            #     epoch_samples += inputs.size(0)

            print_metrics(metrics, epoch_samples, phase)
            epoch_loss = metrics['loss'] / epoch_samples

            if phase == 'val' and epoch_loss < best_loss:
                print("saving best model")
                best_loss = epoch_loss
                best_model_wts = copy.deepcopy(model.state_dict())

        time_elapsed = time.time() - since
        print('{:.0f}m {:.0f}s'.format(time_elapsed // 60, time_elapsed % 60))

    print('Best val loss: {:4f}'.format(best_loss))

    model.load_state_dict(best_model_wts)
    return model


def run(UNet):
    num_class = 1
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    
    model = UNet(num_class).to(device)

#Optimizer
    optimizer_ft = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=1e-4)

    exp_lr_scheduler = lr_scheduler.StepLR(optimizer_ft, step_size=30, gamma=0.1)

    model = train_model(model, optimizer_ft, exp_lr_scheduler, num_epochs=1)

    model.eval()

    trans = v2.Compose([
    v2.ToPureTensor(),
    BinningTransform(bin_size=2),  # Beispiel für Binning mit bin_size 2
    v2.ToDtype(torch.float32, scale=True),
    #PatchTransform(patch_size=64),  # Beispiel für das Aufteilen in Patches der Größe 64x64
    ])

    # # Create another simulation dataset for test
    test_dataset = CustomDataset('data', transform=trans,mapping=MAPPING)
    test_loader = datasets.custom_dataset.DataLoader(test_dataset, batch_size=4, shuffle=True,collate_fn=custom_collate_fn)

    inputs, labels = next(iter(test_loader))
    inputs = inputs.to(device)
    labels = labels.to(device)

    pred = model(inputs)
    pred = F.sigmoid(pred)
    pred = pred.data.cpu().numpy()
    print(pred.shape)

    # # Change channel-order and make 3 channels for matplot
    # input_images_rgb = [GenerateData.reverse_transform(x) for x in inputs.cpu()]
    
    # # Map each channel (i.e. class) to each color
    # target_masks_rgb = [GenerateData.masks_to_colorimg(x) for x in labels.cpu().numpy()]
    
    # pred_rgb = [GenerateData.masks_to_colorimg(x) for x in pred]
    

    # GenerateData.plot_side_by_side([input_images_rgb, target_masks_rgb, pred_rgb])

if __name__ == '__main__':
    try:
        run(UNet)

    except Exception as e:
        print(f"An error occurred: {e}")