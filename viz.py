import argparse
import copy
import numpy as np
import os
import pickle

import torch
import torch.nn as nn

import torchvision
from torchvision import datasets, transforms

import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt

import resnet

parser = argparse.ArgumentParser(description='ImageNet Resnet Loss Landscape')
parser.add_argument('model1', type=str, help="Model1 checkpoint")
parser.add_argument('model2', type=str, help="Model2 checkpoint")
parser.add_argument('--batch-size', type=int, default=100)
parser.add_argument('--viz-samples', type=int, default=200, help="# of interpolants to sample")
parser.add_argument('--data-dir', type=str, default='/rscratch/imagenet12_data')
parser.add_argument('--output-dir', type=str, default='output')
parser.add_argument('--arch', type=str, default='resnet18', choices=['resnet18', 'resnet34', 'resnet50', 'resnet101', 'resnet152'], help="ResNet architecture")
parser.add_argument('--test-samples', type=int, default=50000, help="# testing samples to evaluate")
parser.add_argument('--disable-cuda', action='store_true')

args = parser.parse_args()

torch.manual_seed(0)
if not args.disable_cuda and torch.cuda.is_available():
    device = torch.device("cuda")
    torch.cuda.manual_seed_all(0)
else:
    device = torch.device("cpu")


def accuracy(output, target, topk=(1,)):
    """Computes the precision@k for the specified values of k"""
    with torch.no_grad():
        maxk = max(topk)

        _, pred = output.topk(maxk, 1, True, True)
        pred = pred.t()
        correct = pred.eq(target.view(1, -1).expand_as(pred))

        res = []
        for k in topk:
            correct_k = correct[:k].view(-1).float().sum(0, keepdim=True)
            res.append(correct_k)
        return res


def interpolate(model1, model2, alpha):
    ret = copy.deepcopy(model1)

    for param1, param2 in zip(ret.parameters(), model2.parameters()):
        param1.requires_grad = False
        param1.data = alpha * param1.data + (1 - alpha) * param2.data

    return ret


def visualize(model1, model2, testloader, trainloader, viz_samples, test_samples):
    test_losses = []
    test_acces = []

    train_losses = []
    train_acces = []

    alphas = np.linspace(-1, 2, num=viz_samples)

    criterion = nn.CrossEntropyLoss()
    for i, alpha in enumerate(alphas):
        print("Testing perturbation {}/{}".format(i+1, viz_samples))
        interpolant = interpolate(model1, model2, alpha)

        test_loss, test_acc = test(testloader, interpolant, criterion, test_samples)
        train_loss, train_acc = test(trainloader, interpolant, criterion, test_samples)
        
        test_losses.append(test_loss)
        test_acces.append(test_acc)

        train_losses.append(train_loss)
        train_acces.append(train_acc)

    with open(os.path.join(args.output_dir, "raw_arrays"), "wb") as f:
        d = {
                "test loss": test_losses,
                "test accuracy": test_acces,
                "train loss": train_losses,
                "train accuracy": train_acces,
            }
        pickle.dump(d, f)

    plt.plot(alphas, train_losses, label="Train Loss")
    plt.plot(alphas, test_losses, label="Test Loss")
    plt.xlabel(u"\u03B1 (\u03B8' = \u03B1 * w1 + (1 - \u03B1) * w2)")
    plt.ylabel("Cross Entropy Loss")
    plt.yscale('log')
    plt.legend()
    plt.grid()
    plt.savefig(os.path.join(args.output_dir, "loss.pdf"), dpi=150)

    plt.clf()

    plt.plot(alphas, train_acces, label="Train Acc")
    plt.plot(alphas, test_acces, label="Test Acc")
    plt.xlabel(u"\u03B1 (\u03B8' = \u03B1 * w1 + (1 - \u03B1) * w2)")
    plt.ylabel("Top 1 Accuracy %")
    plt.axis([-1, 2, 0, 100]) 
    plt.legend()
    plt.grid()
    plt.savefig(os.path.join(args.output_dir, "acc.pdf"), dpi=150)


def test(loader, model, criterion, samples):
    model.eval()
   
    total_loss = 0.
    total_acc = 0
    total = 0

    for inputs, targets in loader:
        if total >= samples:
            break

        inputs, targets = inputs.to(device), targets.to(device)

        outputs = model(inputs)
        loss = criterion(outputs, targets)
        acc = accuracy(outputs, targets)[0]

        total_loss += loss.item()
        total_acc += acc
        total += targets.size(0)

    return total_loss / total, 100 * total_acc / total 


print('Loading data')

traindir = os.path.join(args.data_dir, 'train')
valdir = os.path.join(args.data_dir, 'val')

normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225])
transform_train=transforms.Compose([
        transforms.RandomResizedCrop(224,scale=(0.1,1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        normalize,
    ])
transform_test = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            normalize,
        ])

trainset = datasets.ImageFolder(traindir, transform_train)
testset = datasets.ImageFolder(valdir, transform_test)

trainloader = torch.utils.data.DataLoader(trainset, batch_size=args.batch_size, shuffle=True, pin_memory=True, num_workers=30)
testloader = torch.utils.data.DataLoader(testset, batch_size=args.batch_size, shuffle=False, pin_memory=True, num_workers=30)

print('Loading models')

model = getattr(resnet, args.arch)
model1 = model()
model2 = model()

checkpoint1 = torch.load(args.model1)
checkpoint2 = torch.load(args.model2)

model1.load_state_dict(checkpoint1['state_dict'])
model2.load_state_dict(checkpoint2['state_dict'])

model1 = model1.to(device)
model2 = model2.to(device)

visualize(model1, model2, testloader, trainloader, args.viz_samples, args.test_samples)

