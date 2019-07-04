import os
import torch
import argparse
import numpy as np
import torch.nn as nn
from tqdm import tqdm
from torch import optim
import torch.nn.functional as F
from torchvision import datasets
from torchvision import transforms
from skimage.io import imsave
import matplotlib.pyplot as plt
from torchvision.utils import make_grid
from torchvision.utils import save_image
from skimage.exposure import rescale_intensity


class D(nn.Module):
    def __init__(self, input_size, num_classes):
        super(D, self).__init__()
        self.fc1 = nn.Linear(input_size, 1024)
        self.fc2 = nn.Linear(self.fc1.out_features, 512)
        self.fc3 = nn.Linear(self.fc2.out_features, 256)
        self.fc4 = nn.Linear(self.fc3.out_features, num_classes)
        self.label_emb = nn.Embedding(10, 10)

    def forward(self, x, labels):
        x = x.view(x.size(0), 28*28)
        c = self.label_emb(labels)
        c = torch.squeeze(c)
        x = torch.cat([x, c], 1)
        x = F.relu(self.fc1(x), 0.2)
        x = F.relu(self.fc2(x), 0.2)
        x = F.relu(self.fc3(x), 0.2)
        return torch.sigmoid(self.fc4(x))

class G(nn.Module):
    def __init__(self, input_size, n_class):
        super(G, self).__init__()
        self.fc1 = nn.Linear(input_size, 1024)
        self.fc2 = nn.Linear(self.fc1.out_features, 512)
        self.fc3 = nn.Linear(self.fc2.out_features, 256)
        self.fc4 = nn.Linear(self.fc3.out_features, n_class)
        self.label_emb = nn.Embedding(10, 10)

    def forward(self, x, labels):
        x = x.view(x.size(0), 100)
        c = self.label_emb(labels)
        c = torch.squeeze(c)
        x = torch.cat([x, c], 1)
        x = F.relu(self.fc1(x), 0.2)
        x = F.relu(self.fc2(x), 0.2)
        x = F.relu(self.fc3(x), 0.2)
        x = torch.tanh(self.fc4(x))
        return x.view(x.size(0), 28, 28)


class MNISTGAN:
    def __init__(self, experiment):
        self.batch_size = 128
        self.lr = 1e-4
        self.epochs = 100
        self.z_dim = 100
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=(0.5,), std=(0.5,))
        ])
        self.train_dataset = datasets.MNIST(root='/data', train=True, download=True, transform=transform)
        self.train_loader = torch.utils.data.DataLoader(dataset=self.train_dataset, batch_size=self.batch_size, shuffle=True)
        self.mnist_dim = self.train_dataset.train_data.size(1) * self.train_dataset.train_data.size(2)
        self.d = D(self.mnist_dim+10, 1)
        self.d.cuda()
        self.g = G(self.z_dim+10, self.mnist_dim)
        self.g.cuda()
        self.loss = nn.BCELoss()
        self.g_opt = optim.Adam(self.g.parameters(), lr=self.lr)
        self.d_opt = optim.Adam(self.d.parameters(), lr=self.lr)
        self.experiment = experiment
        exp_dir = os.path.join('experiments', experiment)
        self.images_dir = os.path.join(exp_dir, 'images')
        if not os.path.exists(self.images_dir):
            os.makedirs(self.images_dir)

    def train_d(self, x, labels):
        self.d.zero_grad()

        x = x.cuda()
        labels = labels.long().cuda()

        output = self.d(x, labels)
        y_real = torch.FloatTensor(x.shape[0], 1).uniform_(0, 0.1)
        y_real = y_real.cuda()
        real_loss = self.loss(output, y_real)
        
        z = torch.FloatTensor(self.batch_size, self.z_dim).normal_()
        z = z.cuda()
        fake_labels = torch.FloatTensor(self.batch_size, 1).random_(0, 10)
        fake_labels = fake_labels.long().cuda()
        fake_images = self.g(z, fake_labels)

        output = self.d(fake_images, fake_labels)
        y_fake = torch.FloatTensor(self.batch_size, 1).uniform_(0.9, 1)
        y_fake = y_fake.cuda()
        fake_loss = self.loss(output, y_fake)

        d_loss = real_loss + fake_loss
        d_loss.cuda()
        d_loss.backward()
        self.d_opt.step()

        return d_loss.data.item()

    def train_g(self, x):
        self.g.zero_grad()

        fake_labels = torch.FloatTensor(self.batch_size, 1).random_(0, 10)
        fake_labels = fake_labels.long().cuda()
        z = torch.FloatTensor(fake_labels.shape[0], self.z_dim).normal_()
        z = z.cuda()

        fake_images = self.g(z, fake_labels)
        d_output = self.d(fake_images, fake_labels)
        # g_loss = self.loss(d_output, torch.FloatTensor(fake_labels.shape[0], 1).uniform_(0, 0.1))
        soft_fake_labels = torch.FloatTensor(fake_labels.shape[0], 1).uniform_(0, 0.1)
        soft_fake_labels = soft_fake_labels.cuda()
        g_loss = self.loss(d_output, soft_fake_labels)
        g_loss.cuda()

        g_loss.backward()
        self.g_opt.step()

        return fake_images[:1], fake_labels[:1], g_loss.data.item()


    def train(self):
        t1 = tqdm(range(self.epochs), position=0)
        for epoch in t1:
            for batch_index, (x, y) in tqdm(enumerate(self.train_loader), position=1, total=len(self.train_loader)):
                d_loss = self.train_d(x, y)
                fake_images, fake_labels, g_loss = self.train_g(x)
            self.log_images(fake_images, fake_labels, epoch)
            t1.set_description(f'D: {d_loss:.2f} | G: {g_loss:.2f}')
        while True:
            digit = input('Enter a number between 0 and 9: ')
            digit = torch.FloatTensor([[int(digit), 5]])
            digit = digit.long().cuda()
            z = torch.FloatTensor(2, self.z_dim).normal_()
            z = z.cuda()
            generated_image = self.g(z, digit)[0].cpu().detach().numpy()
            generated_image = rescale_intensity(generated_image, out_range=(0, 255)).astype(np.uint16)
            plt.imshow(generated_image)
            plt.show()


    def log_images(self, imgs, labels, epoch):
        labels = [label.cpu().detach().numpy() for label in labels]
        label = labels[0][0]
        im_name = os.path.join(self.images_dir, f'epoch{epoch}_digit{label}.png')
        imgs = [img.cpu().detach().numpy() for img in imgs]
        imgs = [rescale_intensity(img, out_range=(0, 255)).astype(np.uint16) for img in imgs]
        imgs = np.hstack(imgs)
        imsave(im_name, imgs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment')
    args = parser.parse_args()
    gan = MNISTGAN(args.experiment)
    gan.train()

