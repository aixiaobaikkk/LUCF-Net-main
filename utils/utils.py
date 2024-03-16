
import torch
import torch.nn as nn
import numpy as np
from medpy import metric
from scipy.ndimage import zoom
import seaborn as sns

import SimpleITK as sitk
import pandas as pd


from thop import profile
from thop import clever_format


def clip_gradient(optimizer, grad_clip):
    """
    For calibrating misalignment gradient via cliping gradient technique
    :param optimizer:
    :param grad_clip:
    :return:
    """
    for group in optimizer.param_groups:
        for param in group['params']:
            if param.grad is not None:
                param.grad.data.clamp_(-grad_clip, grad_clip)


def adjust_lr(optimizer, init_lr, epoch, decay_rate=0.1, decay_epoch=30):
    decay = decay_rate ** (epoch // decay_epoch)
    for param_group in optimizer.param_groups:
        param_group['lr'] *= decay


class AvgMeter(object):
    def __init__(self, num=40):
        self.num = num
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0
        self.losses = []

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count
        self.losses.append(val)

    def show(self):
        return torch.mean(torch.stack(self.losses[np.maximum(len(self.losses)-self.num, 0):]))


def CalParams(model, input_tensor):
    """
    Usage:
        Calculate Params and FLOPs via [THOP](https://github.com/Lyken17/pytorch-OpCounter)
    Necessarity:
        from thop import profile
        from thop import clever_format
    :param model:
    :param input_tensor:
    :return:
    """
    flops, params = profile(model, inputs=(input_tensor,))
    flops, params = clever_format([flops, params], "%.3f")
    print('[Statistics Information]\nFLOPs: {}\nParams: {}'.format(flops, params))
    
def one_hot_encoder(input_tensor,dataset,n_classes = None):
    tensor_list = []
    if dataset == 'MMWHS':  
        dict = [0,205,420,500,550,600,820,850]
        for i in dict:
            temp_prob = input_tensor == i  
            tensor_list.append(temp_prob.unsqueeze(1))
        output_tensor = torch.cat(tensor_list, dim=1)
        return output_tensor.float()
    else:
        for i in range(n_classes):
            temp_prob = input_tensor == i  
            tensor_list.append(temp_prob.unsqueeze(1))
        output_tensor = torch.cat(tensor_list, dim=1)
        return output_tensor.float()    



def calculate_metric_percase(pred, gt):
    pred[pred > 0] = 1
    gt[gt > 0] = 1
    if pred.sum() > 0 and gt.sum()>0:
        #
        dice = metric.binary.dc(pred, gt)
        hd95 = metric.binary.hd95(pred, gt)
        jaccard = metric.binary.jc(pred, gt)
        asd = metric.binary.assd(pred, gt)


        return dice, hd95, jaccard, asd
    elif pred.sum() > 0 and gt.sum()==0:
        return 1, 0, 1, 0
    else:
        return 0, 0, 0, 0

def calculate_dice_percase(pred, gt):
    pred[pred > 0] = 1
    gt[gt > 0] = 1
    if pred.sum() > 0 and gt.sum()>0:
        dice = metric.binary.dc(pred, gt)
        return dice
    elif pred.sum() > 0 and gt.sum()==0:
        return 1
    else:
        return 0


def test_single_volume(image, label, net, classes, patch_size=[256, 256], test_save_path=None, case=None, z_spacing=1,model_name='LUCF_Net'):
    image, label = image.squeeze(0).cpu().detach().numpy(), label.squeeze(0).cpu().detach().numpy()

    if len(image.shape) == 3:
        prediction = np.zeros_like(label)
        for ind in range(image.shape[0]):
            slice = image[ind, :, :]
            x, y = slice.shape[0], slice.shape[1]
            if x != patch_size[0] or y != patch_size[1]:
                slice = zoom(slice, (patch_size[0] / x, patch_size[1] / y), order=3)  # previous using 0
            input = torch.from_numpy(slice).unsqueeze(0).unsqueeze(0).float().cuda()

            net.eval()
            with torch.no_grad():
                if model_name == 'Exp_Net_fusion' :
                    p1, p2, p3, p4, = net(input)
                    outputs = p1 + p2 + p3 + p4
                elif model_name == 'Exp_Net':
                    p1,p2,p3,p4 = net(input)
                    outputs = p4
                elif model_name == '2':
                    p1, p2, p3, p4 = net(input)
                    outputs = p3+p4
                elif model_name == '3':
                    p1, p2, p3, p4 = net(input)
                    outputs = p4+p3+p2

                else:

                    p1, p2, p3, p4, = net(input)
                    outputs = p1 + p2 + p3 + p4
                out = torch.argmax(torch.softmax(outputs, dim=1), dim=1).squeeze(0)
                out = out.cpu().detach().numpy()
                if x != patch_size[0] or y != patch_size[1]:
                    pred = zoom(out, (x / patch_size[0], y / patch_size[1]), order=0)
                else:
                    pred = out
                prediction[ind] = pred
    else:
        input = torch.from_numpy(image).unsqueeze(
            0).unsqueeze(0).float().cuda()
        net.eval()
        with torch.no_grad():
            if model_name == 'LUCF_Net' or model_name == 'PVT_Cascade' :
                p1, p2, p3, p4, = net(input)
                outputs = p1 + p2 + p3 + p4
            elif model_name == 'Exp_Net':
                p1, p2, p3, p4, = net(input)
                outputs = p4
            else:
                outputs = net(input)
            out = torch.argmax(torch.softmax(outputs, dim=1), dim=1).squeeze(0)
            prediction = out.cpu().detach().numpy()
    metric_list = []

    for i in range(1, classes):
        metric_list.append(calculate_metric_percase(prediction == i, label == i))

    # if test_save_path is not None:
    #     img_itk = sitk.GetImageFromArray(image.astype(np.float32))
    #     prd_itk = sitk.GetImageFromArray(prediction.astype(np.float32))
    #     lab_itk = sitk.GetImageFromArray(label.astype(np.float32))
    #     img_itk.SetSpacing((1, 1, z_spacing))
    #     prd_itk.SetSpacing((1, 1, z_spacing))
    #     lab_itk.SetSpacing((1, 1, z_spacing))
    #     sitk.WriteImage(prd_itk, test_save_path + '/'+case + "_pred.nii.gz")
    #     sitk.WriteImage(img_itk, test_save_path + '/'+ case + "_img.nii.gz")
    #     sitk.WriteImage(lab_itk, test_save_path + '/'+ case + "_gt.nii.gz")
    return metric_list

def val_single_volume(image, label, net, classes, patch_size=[256, 256], test_save_path=None, case=None, z_spacing=1,model_name='LUCF_Net'):
    image, label = image.squeeze(0).cpu().detach().numpy(), label.squeeze(0).cpu().detach().numpy()
    if len(image.shape) == 3:
        prediction = np.zeros_like(label)
        for ind in range(image.shape[0]):
            slice = image[ind, :, :]
            x, y = slice.shape[0], slice.shape[1]
            if x != patch_size[0] or y != patch_size[1]:
                slice = zoom(slice, (patch_size[0] / x, patch_size[1] / y), order=3)  # previous using 0
            input = torch.from_numpy(slice).unsqueeze(0).unsqueeze(0).float().cuda()
            net.eval()
            with torch.no_grad():
                p1, p2, p3, p4, = net(input)
                outputs = p1 + p2 + p3 + p4
                out = torch.argmax(torch.softmax(outputs, dim=1), dim=1).squeeze(0)
                out = out.cpu().detach().numpy()
                if x != patch_size[0] or y != patch_size[1]:
                    pred = zoom(out, (x / patch_size[0], y / patch_size[1]), order=0)
                else:
                    pred = out
                prediction[ind] = pred
    else:
        input = torch.from_numpy(image).unsqueeze(
            0).unsqueeze(0).float().cuda()
        net.eval()
        with torch.no_grad():
            p1, p2, p3, p4, = net(input)
            outputs = p1 + p2 + p3 + p4
            out = torch.argmax(torch.softmax(outputs, dim=1), dim=1).squeeze(0)
            prediction = out.cpu().detach().numpy()
    metric_list = []
    for i in range(1, classes):
        metric_list.append(calculate_dice_percase(prediction == i, label == i))
    return metric_list

