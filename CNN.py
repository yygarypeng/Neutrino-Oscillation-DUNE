# %% [code] {"jupyter":{"outputs_hidden":false}}
import gc

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf

# check the tensorflow and GPU

print(f"Using Tensorflow {tf.__version__}")
device_name = tf.test.gpu_device_name()
if device_name != "/device:GPU:0":
    raise SystemError("GPU device not found")
print(
    f"Found GPU adn CPU.\nTensorFlow has access to the following devices:\n{tf.config.list_physical_devices()}"
)


# import the datasets and check the files

import os

# path = "./phys591000-2023-final-project/"  # run on the local machine
# path = "/content/drive/Shareddrives/2023AI_final/2023AI_final/phys591000-2023-final-project/" # run on the google colab
path = "/kaggle/input/dune-neutrino/"  # Kaggle
if not os.path.isfile(path + "neutrino_test_data.npz") or os.path.isfile(
    path + "neutrino_train_data.npz"
):
    raise FileNotFoundError("test/train data was not found or is a directory")

# take out data from the datasets

data_train = np.load(path + "neutrino_training_data.npz")  # ideal data
data_test = np.load(path + "neutrino_test_data.npz")  # pseudo-exp data

name_train = data_train.files
name_test = data_test.files

(
    ve_train,
    vebar_train,
    vu_train,
    vubar_train,
    theta23_train,
    delta_train,
    ldm_train,
) = map(lambda n: data_train[n], name_train)
ve_test, vebar_test, vu_test, vubar_test = map(lambda n: data_test[n], name_test)


# create train and test data
X_train = np.stack((ve_train, vebar_train, vu_train, vubar_train), axis=-1)
Y_train = np.stack((theta23_train, delta_train, ldm_train), axis=-1)
# X_test = np.stack((ve_test, vebar_test, vu_test, vubar_test), axis=-1)

# [X] normalize training data to [0,1]
x_train_NH = X_train[ldm_train > 0]
print(f"Before normalized, the shape of x_train: {x_train_NH.shape}")
v_max = np.max(x_train_NH)
v_min = np.min(x_train_NH)
print(f"X-train normalized factors (v_max, v_min) = ({v_max}, {v_min})")
x_train_NH_norm = (x_train_NH - v_min) / (v_max - v_min)
print(f"After normalized, the shape of x_train: {x_train_NH_norm.shape}")
# [Y] normalize training label to [0,1]
y_train_NH = Y_train[:, 0][ldm_train > 0]
print(f"Before normalized, the shape of y_train: {y_train_NH.shape}")
v_max = np.max(y_train_NH)
v_min = np.min(y_train_NH)
y_train_NH_norm = (y_train_NH - v_min) / (v_max - v_min)
print(f"Y-train normalized factors (v_max, v_min) = ({v_max}, {v_min})")
print(f"After normalized, the shape of y_train: {y_train_NH_norm.shape}")

# clear unused variables
del (
    X_train,
    Y_train,
    ve_train,
    vebar_train,
    vu_train,
    vubar_train,
    theta23_train,
    delta_train,
    ldm_train,
    ve_test,
    vebar_test,
    vu_test,
    vubar_test,
)
gc.collect()

# create validation data
from sklearn.model_selection import train_test_split

# split the training dataset into training and validation, with test_size = 0.2
tf.random.set_seed(2023)
x_train, x_val, y_train, y_val = train_test_split(
    x_train_NH_norm,
    y_train_NH_norm,
    test_size=0.2,
    shuffle=True,
)
# clear unused variables
del x_train_NH_norm, y_train_NH_norm

from tensorflow.keras import Input, Model
from tensorflow.keras import backend as K
from tensorflow.keras import regularizers
from tensorflow.keras.layers import (
    AveragePooling2D,
    BatchNormalization,
    Conv2D,
    Conv2DTranspose,
    Dense,
    Dropout,
    Flatten,
    Lambda,
    Layer,
    LeakyReLU,
    Reshape,
)


def create_model_cvae(input_dim, latent_dim):
    def conv2d(inputs, filters, kernel_size):
        x = Conv2D(filters, kernel_size=kernel_size, strides=1, padding="same")(inputs)
        x = BatchNormalization()(x)
        x = LeakyReLU(alpha=0.2)(x)
        x = Conv2D(filters, kernel_size=kernel_size, strides=1, padding="same")(x)
        x = BatchNormalization()(x)
        x = LeakyReLU(alpha=0.2)(x)
        x = AveragePooling2D(pool_size=(2, 2))(x)
        return x

    # Encoder
    inputs = Input(shape=input_dim)
    x = conv2d(inputs, filters=64, kernel_size=4)
    x = conv2d(x, filters=32, kernel_size=4)
    x = Flatten()(x)
    x = Dense(256, kernel_regularizer=regularizers.l2(0.002), activation="elu")(x)
    x = Dense(64, kernel_regularizer=regularizers.l2(0.002), activation="elu")(x)
    x = Dense(16, kernel_regularizer=regularizers.l2(0.002), activation="elu")(x)
    x = Dense(1, activation="relu")(x)
    dcnn = Model(inputs, x, name="dnn")
    dcnn.summary()

    # CVAE + DNN
    model_inputs = Input(shape=input_dim)
    fin_dnn = dcnn(model_inputs)
    dcnn = Model(inputs=model_inputs, outputs=fin_dnn)
    return dcnn


from tensorflow.keras.optimizers import Adam

# Declare the model
cvae = create_model_cvae(
    input_dim=(x_train.shape[1], x_train.shape[2], 1), latent_dim=2
)

# Compile the model
cvae.compile(optimizer=Adam(5e-6), loss="huber")


from tensorflow.keras.callbacks import EarlyStopping

# train
early_stopping = EarlyStopping(
    monitor="val_loss",
    min_delta=0.005,
    patience=30,
    mode="auto",
    baseline=None,
    restore_best_weights=False,
)

cvae.fit(
    x=x_train,
    y=y_train,
    validation_data=(x_val, y_val),
    epochs=256,
    batch_size=64,
    callbacks=[early_stopping],
    shuffle=True,
    verbose=2,
)

# check the loss function
fig = plt.figure(figsize=(8, 5), dpi=120)
history = cvae.history.history
plt.plot(history["loss"], lw=2.5, label="Train", alpha=0.8)
plt.plot(history["val_loss"], lw=2.5, label="Validation", alpha=0.8)
plt.title("Epoch vs Huber loss")
plt.xlabel("epoch")
plt.ylabel("Loss (Huber)")
plt.legend(loc="best")
plt.savefig("CVAE_loss.png")
plt.close()

# save model
cvae.save("./CVAE_Theta23.h5")
