# -*- coding: utf-8 -*-
# @Date    : 2019-08-02
# @Author  : Xinyu Gong (xy_gong@tamu.edu)
# @Link    : None
# @Version : 0.0

from torch import nn
import torch.nn.functional as F

# Generator
CONV_TYPE = {0: 'post', 1: 'pre'}
NORM_TYPE = {0: None, 1: 'bn', 2: 'in'}
UP_TYPE = {0: 'bilinear', 1: 'nearest', 2: 'deconv'}
SHORT_CUT_TYPE = {0: False, 1: True}
SKIP_TYPE = {0: False, 1: True}  # 共用

# Discriminator
# NORM_TYPE = {0: None, 1: 'bn', 2: 'in'}
DISCONV_TYPE = {0:'sep_conv_3x3',1:'sep_conv_5x5',2:'dil_conv_3x3',3:'dil_conv_5x5',4:'max_pool_3x3',5:'avg_pool_3x3'}
# SKIP_TYPE = {0: False, 1: True}

def decimal2binary(n):
    return bin(n).replace("0b", "")


class PreGenBlock(nn.Module):
    def __init__(self, in_channels, out_channels, up_block, ksize=3):
        super(PreGenBlock, self).__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, ksize, padding=ksize//2)
        self.bn = nn.BatchNorm2d(in_channels)
        self.inn = nn.InstanceNorm2d(in_channels)
        self.up_block = up_block
        self.deconv = nn.ConvTranspose2d(
            in_channels, out_channels, kernel_size=2, stride=2)

    def set_arch(self, up_id, norm_id):
        self.up_type = UP_TYPE[up_id]
        self.norm_type = NORM_TYPE[norm_id]

    def forward(self, x):
        # norm
        if self.norm_type:
            if self.norm_type == 'bn':
                h = self.bn(x)
            elif self.norm_type == 'in':
                h = self.inn(x)
            else:
                raise NotImplementedError(self.norm_type)
        else:
            h = x

        # activation
        h = nn.ReLU()(h)

        # whether this is a upsample block
        if self.up_block:
            if self.up_type == 'deconv':
                h = self.deconv(h)
            else:
                h = F.interpolate(h, scale_factor=2, mode=self.up_type)

        # conv
        out = self.conv(h)
        return out


class PostGenBlock(nn.Module):
    def __init__(self, in_channels, out_channels, up_block, ksize=3):
        super(PostGenBlock, self).__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, ksize, padding=ksize//2)
        self.bn = nn.BatchNorm2d(out_channels)
        self.inn = nn.InstanceNorm2d(out_channels)
        self.up_block = up_block
        self.deconv = nn.ConvTranspose2d(
            in_channels, out_channels, kernel_size=2, stride=2)

    def set_arch(self, up_id, norm_id):
        self.up_type = UP_TYPE[up_id]
        self.norm_type = NORM_TYPE[norm_id]

    def forward(self, x):
        # whether this is a upsample block
        if self.up_block:
            if self.up_type == 'deconv':
                h = self.deconv(x)
            else:
                h = F.interpolate(x, scale_factor=2, mode=self.up_type)
        else:
            h = x

        # conv
        h = self.conv(h)

        # norm
        if self.norm_type:
            if self.norm_type == 'bn':
                h = self.bn(h)
            elif self.norm_type == 'in':
                h = self.inn(h)
            else:
                raise NotImplementedError(self.norm_type)

        # activation
        out = nn.ReLU()(h)

        return out


class Cell(nn.Module):
    def __init__(self, in_channels, out_channels, num_skip_in, ksize=3):
        super(Cell, self).__init__()
        # 细节是1是上采样的一层而2的up_block为False,up_id只是判断上采样的类型，实际是否上采样是自己规定的
        self.post_conv1 = PostGenBlock(in_channels, out_channels, ksize=ksize, up_block=True)
        self.pre_conv1 = PreGenBlock(in_channels, out_channels, ksize=ksize, up_block=True)

        self.post_conv2 = PostGenBlock(out_channels, out_channels, ksize=ksize, up_block=False)
        self.pre_conv2 = PreGenBlock(in_channels, out_channels, ksize=ksize, up_block=False)

        self.deconv_sc = nn.ConvTranspose2d(
            in_channels, out_channels, kernel_size=2, stride=2)
        self.c_sc = nn.Conv2d(in_channels, out_channels, kernel_size=1)

        # skip_in
        self.skip_deconvx2 = nn.ConvTranspose2d(in_channels, out_channels, kernel_size=2, stride=2)
        self.skip_deconvx4 = nn.Sequential(
            nn.ConvTranspose2d(in_channels, out_channels, kernel_size=2, stride=2),
            nn.ConvTranspose2d(in_channels, out_channels, kernel_size=2, stride=2)
        )

        self.num_skip_in = num_skip_in
        if num_skip_in:
            self.skip_in_ops = nn.ModuleList([nn.Conv2d(in_channels, out_channels, kernel_size=1) for _ in range(num_skip_in)])

    def set_arch(self, conv_id, norm_id, up_id, short_cut_id, skip_ins):
        self.post_conv1.set_arch(up_id, norm_id)
        self.pre_conv1.set_arch(up_id, norm_id)
        self.post_conv2.set_arch(up_id, norm_id)
        self.pre_conv2.set_arch(up_id, norm_id)

        if self.num_skip_in:
            self.skip_ins = [0 for _ in range(self.num_skip_in)]
            for skip_idx, skip_in in enumerate(decimal2binary(skip_ins)[::-1]):
                self.skip_ins[-(skip_idx + 1)] = int(skip_in)

        self.conv_type = CONV_TYPE[conv_id]
        self.up_type = UP_TYPE[up_id]
        self.short_cut = SHORT_CUT_TYPE[short_cut_id]

    def forward(self, x, skip_ft=None):
        residual = x

        # first conv
        if self.conv_type == 'post':
            h = self.post_conv1(residual)
        elif self.conv_type == 'pre':
            h = self.pre_conv1(residual)
        else:
            raise NotImplementedError(self.norm_type)
        _, _, ht, wt = h.size()
        h_skip_out = h  # first conv之后可能会跳出进行skip_connection操作
        # second conv
        if self.num_skip_in:
            assert len(self.skip_in_ops) == len(self.skip_ins)
            for skip_flag, ft, skip_in_op in zip(self.skip_ins, skip_ft, self.skip_in_ops):
                if skip_flag:
                    if self.up_type != 'deconv':
                        h += skip_in_op(F.interpolate(ft, size=(ht, wt), mode=self.up_type))
                    else:
                        scale = wt // ft.size()[-1]
                        h += skip_in_op(getattr(self, f'skip_deconvx{scale}')(ft))

        if self.conv_type == 'post':
            final_out = self.post_conv2(h)
        elif self.conv_type == 'pre':
            final_out = self.pre_conv2(h)
        else:
            raise NotImplementedError(self.norm_type)

        # shortcut 这里不应该是self.short_cut吗？？？
        if self.c_sc:
            if self.up_type != 'deconv':
                final_out += self.c_sc(F.interpolate(x, scale_factor=2, mode=self.up_type))
            else:
                final_out += self.c_sc(self.deconv_sc(x))

        return h_skip_out, final_out


class DisCell(nn.Module):
    def __init__(self, args, in_channels, out_channels, hidden_channels=None,
            kernel_size=3,
            padding=1,
            activation=nn.ReLU(),
            downsample=False):
        super(DisCell, self).__init__()
        self.c1 = nn.Conv2d(
            in_channels,
            out_channels,
            kernel_size=3,
            padding=1)
        self.c2 = nn.Conv2d(
            out_channels,
            out_channels,
            kernel_size=3,
            padding=1)
        if args.d_spectral_norm:
            self.c1 = nn.utils.spectral_norm(self.c1)
            self.c2 = nn.utils.spectral_norm(self.c2)
        self.bn = nn.BatchNorm2d(out_channels)
        self.inn = nn.InstanceNorm2d(out_channels)
        self.activation = activation
        self.downsample = downsample
        self.learnable_sc = (in_channels != out_channels) or downsample
        self.in_channels = in_channels
        self.out_channels = out_channels
        hidden_channels = in_channels if hidden_channels is None else hidden_channels

        # sep3
        self.disconv1 = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=2, padding=1, bias=False),
            nn.Conv2d(out_channels, out_channels, kernel_size=1, padding=0, bias=False))
        # sep5
        self.disconv2 = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(out_channels, out_channels, kernel_size=5, stride=2, padding=2, bias=False),
            nn.Conv2d(out_channels, out_channels, kernel_size=1, padding=0, bias=False))
        # dil3
        self.disconv3 = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=2, padding=2,
                      dilation=2, bias=False),
            nn.Conv2d(out_channels, out_channels, kernel_size=1, padding=0, bias=False))
        # dil5
        self.disconv4 = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(out_channels, out_channels, kernel_size=5, stride=2, padding=4,
                      dilation=2, bias=False),
            nn.Conv2d(out_channels, out_channels, kernel_size=1, padding=0, bias=False))
        # self.avgpool = nn.Sequential(nn.AvgPool2d(3, stride=2, padding=1, count_include_pad=False),
        #                              nn.Conv2d(in_channels, out_channels, kernel_size=1))
        # self.maxpool = nn.Sequential(nn.MaxPool2d(3, stride=2, padding=1),
        #                              nn.Conv2d(in_channels, out_channels, kernel_size=1))
        # normal_cell
        self.normal_conv1 = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(self.out_channels, self.out_channels, kernel_size=3, stride=1, padding=1, bias=False),
            nn.Conv2d(self.out_channels, self.out_channels, kernel_size=1, padding=0, bias=False))

        self.normal_conv2 = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(self.out_channels, self.out_channels, kernel_size=5, stride=1, padding=2, bias=False),
            nn.Conv2d(self.out_channels, self.out_channels, kernel_size=1, padding=0, bias=False))

        self.normal_conv3 = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(self.out_channels, self.out_channels, kernel_size=3, stride=1, padding=2,
                      dilation=2, bias=False),
            nn.Conv2d(self.out_channels, self.out_channels, kernel_size=1, padding=0, bias=False))

        self.normal_conv4 = nn.Sequential(
            nn.ReLU(inplace=False),
            nn.Conv2d(self.out_channels, self.out_channels, kernel_size=5, stride=1, padding=4,
                      dilation=2, bias=False),
            nn.Conv2d(self.out_channels, self.out_channels, kernel_size=1, padding=0, bias=False))

        self.avgpool = nn.AvgPool2d(kernel_size=2)
        self.maxpool = nn.MaxPool2d(kernel_size=2)
        self.c_sc = nn.Conv2d(in_channels, out_channels, kernel_size=1)

    def set_arch(self, disconv_id, norm_id, sc_id):
        self.norm_type = NORM_TYPE[norm_id]
        self.disconv_type = DISCONV_TYPE[disconv_id]
        self.short_cut = SHORT_CUT_TYPE[sc_id]

    def residual(self, x):
        h = x
        h = self.activation(h)
        h = self.c1(h)
        h = self.activation(h)
        h = self.c2(h)
        if self.downsample:
            if self.disconv_type == 'sep_conv_3x3':
                h = self.disconv1(h)
            elif self.disconv_type == 'sep_conv_5x5':
                h = self.disconv2(h)
            elif self.disconv_type == 'dil_conv_3x3':
                h = self.disconv3(h)
            elif self.disconv_type == 'dil_conv_5x5':
                h = self.disconv4(h)
            elif self.disconv_type == 'max_pool_3x3':
                h = self.maxpool(h)
            elif self.disconv_type == 'avg_pool_3x3':
                h = self.avgpool(h)
            else:
                raise NotImplementedError(self.disconv_type)
        else:
            if self.disconv_type == 'sep_conv_3x3':
                h = self.normal_conv1(h)
            elif self.disconv_type == 'sep_conv_5x5':
                h = self.normal_conv2(h)
            elif self.disconv_type == 'dil_conv_3x3':
                h = self.normal_conv3(h)
            elif self.disconv_type == 'dil_conv_5x5':
                h = self.normal_conv4(h)
            elif self.disconv_type == 'max_pool_3x3':
                h = h
            elif self.disconv_type == 'avg_pool_3x3':
                h = h
            else:
                raise NotImplementedError(self.disconv_type)
        return h

    def shortcut(self, x):
        if self.learnable_sc:
            x = self.c_sc(x)
            if self.downsample:
                if self.disconv_type == 'sep_conv_3x3':
                    return self.disconv1(x)
                elif self.disconv_type == 'sep_conv_5x5':
                    return self.disconv2(x)
                elif self.disconv_type == 'dil_conv_3x3':
                    return self.disconv3(x)
                elif self.disconv_type == 'dil_conv_5x5':
                    return self.disconv4(x)
                elif self.disconv_type == 'max_pool_3x3':
                    return self.maxpool(x)
                elif self.disconv_type == 'avg_pool_3x3':
                    return self.avgpool(x)
                else:
                    raise NotImplementedError(self.disconv_type)
            else:
                return x
        else:
            return x

    def forward(self, x):
        h = self.residual(x)
        if self.norm_type:
            if self.norm_type == 'bn':
                h = self.bn(h)
            elif self.norm_type == 'in':
                h = self.inn(h)
            else:
                raise NotImplementedError(self.norm_type)
        if self.short_cut:
            h = h + self.short_cut(x)
        final_out = h
        return final_out


def _downsample(x):
    # Downsample (Mean Avg Pooling with 2x2 kernel)
    return nn.AvgPool2d(kernel_size=2)(x)


class OptimizedDisBlock(nn.Module):
    def __init__(
            self,
            args,
            in_channels,
            out_channels,
            ksize=3,
            pad=1,
            activation=nn.ReLU()):
        super(OptimizedDisBlock, self).__init__()
        self.activation = activation

        self.c1 = nn.Conv2d(
            in_channels,
            out_channels,
            kernel_size=ksize,
            padding=pad)
        self.c2 = nn.Conv2d(
            out_channels,
            out_channels,
            kernel_size=ksize,
            padding=pad)
        self.c_sc = nn.Conv2d(
            in_channels,
            out_channels,
            kernel_size=1,
            padding=0)
        if args.d_spectral_norm:
            self.c1 = nn.utils.spectral_norm(self.c1)
            self.c2 = nn.utils.spectral_norm(self.c2)
            self.c_sc = nn.utils.spectral_norm(self.c_sc)

    def residual(self, x):
        h = x
        h = self.c1(h)
        h = self.activation(h)
        h = self.c2(h)
        h = _downsample(h)
        return h

    def shortcut(self, x):
        return self.c_sc(_downsample(x))

    def forward(self, x):
        h = x
        h = self.c1(h)
        h = self.activation(h)
        h = self.c2(h)
        return self.residual(x) + self.shortcut(x)

class DisBlock(nn.Module):
    def __init__(
            self,
            args,
            in_channels,
            out_channels,
            hidden_channels=None,
            ksize=3,
            pad=1,
            activation=nn.ReLU(),
            downsample=False):
        super(DisBlock, self).__init__()
        self.activation = activation
        self.downsample = downsample
        self.learnable_sc = (in_channels != out_channels) or downsample
        hidden_channels = in_channels if hidden_channels is None else hidden_channels

        self.c1 = nn.Conv2d(
            in_channels,
            hidden_channels,
            kernel_size=ksize,
            padding=pad)
        self.c2 = nn.Conv2d(
            hidden_channels,
            out_channels,
            kernel_size=ksize,
            padding=pad)
        if args.d_spectral_norm:
            self.c1 = nn.utils.spectral_norm(self.c1)
            self.c2 = nn.utils.spectral_norm(self.c2)

        if self.learnable_sc:
            self.c_sc = nn.Conv2d(
                in_channels,
                out_channels,
                kernel_size=1,
                padding=0)
            if args.d_spectral_norm:
                self.c_sc = nn.utils.spectral_norm(self.c_sc)

    def residual(self, x):
        h = x
        h = self.activation(h)
        h = self.c1(h)
        h = self.activation(h)
        h = self.c2(h)
        if self.downsample:
            h = _downsample(h)
        return h

    def shortcut(self, x):
        if self.learnable_sc:
            x = self.c_sc(x)
            if self.downsample:
                return _downsample(x)
            else:
                return x
        else:
            return x

    def forward(self, x):
        return self.residual(x) + self.shortcut(x)
