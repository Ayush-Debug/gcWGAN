import os, sys
sys.path.append(os.getcwd())

import time

import numpy as np
import tensorflow as tf
import data_helpers #SZ change
import tflib as lib
import tflib.ops.linear
import tflib.ops.conv1d
import tflib.plot
import Assessment #SZ add
from Bio.SubsMat import MatrixInfo as matlist #SZ add
import matplotlib.pyplot as plt #SZ add
matrix = matlist.blosum62 #SZ add
import os

test_index = sys.argv[1]

sample_path = 'cWGAN_Validation_Samples/Identity_PaddingRatio_Sample_' + test_index
check_path = '../../Checkpoints/cWGAN/model_' + test_index
#os.system('mkdir ' + sample_path)
if not os.path.exists('cWGAN_Validation_Samples'):
    os.system('mkdir cWGAN_Validation_Samples')
if not os.path.exists(sample_path):
    os.system('mkdir ' + sample_path)
if not os.path.exists('cWGAN_Validation_Results'):
    os.system('mkdir cWGAN_Validation_Results')
	
noise_len = int(test_index.split('_')[-1])
CRITIC_ITERS = int(test_index.split('_')[1])

DATA_DIR = '../../Data/Datasets/Final_Data/'
if len(DATA_DIR) == 0:
    raise Exception('Please specify path to data directory in gan_language.py!')

GENERATE_SIZE = 100
BATCH_SIZE = GENERATE_SIZE * 2 # Batch size
SEQ_LEN = 160 # Sequence length in characters
DIM = 512 # Model dimensionality. This is fairly slow and overfits, even on
          # Billion Word. Consider decreasing for smaller datasets.
LAMBDA = 10 # Gradient penalty lambda hyperparameter.
MAX_N_EXAMPLES = 50000 # Max number of data examples to load. If data loading
                          # is too slow or takes too much RAM, you can decrease
                          # this (at the expense of having less training data).

fold_len = 20 #MK add

lib.print_model_settings(locals().copy())

seqs, folds, folds_dict, charmap, inv_charmap = data_helpers.load_dataset_protein( #MK change
    max_length=SEQ_LEN,
    max_n_examples=MAX_N_EXAMPLES,
    data_dir=DATA_DIR
)
#test_trad = Assessment.file_dic(DATA_DIR+'seq_test_trad',DATA_DIR+'fold_test_trad')

#BATCH_SIZE = 1000
f_s_dic = Assessment.Train_dic(DATA_DIR + 'fold_train',DATA_DIR + 'seq_train') #SZ add
inter_dic = Assessment.Interval_dic(DATA_DIR + 'Interval_1.fa') #SZ add
unique_train = Assessment.file_list(DATA_DIR + 'unique_fold_train') #SZ add
unique_new = Assessment.file_list(DATA_DIR + 'unique_fold_new')  #SZ add
rep_dic = Assessment.representative_dic(DATA_DIR + 'cluster_result_03',f_s_dic)

print 'Data loading successfully!'

def softmax(logits):
    return tf.reshape(
        tf.nn.softmax(
            tf.reshape(logits, [-1, len(charmap)])
        ),
        tf.shape(logits)
    )

def make_noise(shape):
    return tf.random_normal(shape)

def ResBlock(name, inputs):
    output = inputs
    output = tf.nn.relu(output)
    output = lib.ops.conv1d.Conv1D(name+'.1', DIM, DIM, 5, output)
    output = tf.nn.relu(output)
    output = lib.ops.conv1d.Conv1D(name+'.2', DIM, DIM, 5, output)
    return inputs + (0.3*output)

def ResBlock_v2(name, inputs,size): #MK add
    output = inputs
    output = tf.nn.relu(output)
    output = lib.ops.conv1d.Conv1D(name+'.1', size, size, 5, output)
    output = tf.nn.relu(output)
    output = lib.ops.conv1d.Conv1D(name+'.2', size, size, 5, output)
    return inputs + (0.3*output)

def Generator(n_samples, labels, prev_outputs=None): #MK change
    output = make_noise(shape=[n_samples, noise_len])
    output = tf.concat([output,labels],axis=1) #MK add
    output = lib.ops.linear.Linear('Generator.Input', noise_len+fold_len, SEQ_LEN*DIM, output) #MK change
    output = tf.reshape(output, [-1, DIM, SEQ_LEN])
    output = ResBlock('Generator.1', output)
    output = ResBlock('Generator.2', output)
    output = ResBlock('Generator.3', output)
    output = ResBlock('Generator.4', output)
    output = ResBlock('Generator.5', output)
    output = lib.ops.conv1d.Conv1D('Generator.Output', DIM, len(charmap), 1, output)
    output = tf.transpose(output, [0, 2, 1])
    output = softmax(output)
    return output

def Discriminator(inputs,labels): #MK change
    output = tf.transpose(inputs, [0,2,1])
    output = lib.ops.conv1d.Conv1D('Discriminator.Input', len(charmap), DIM, 1, output)
    output = ResBlock('Discriminator.1', output)
    output = ResBlock('Discriminator.2', output)
    output = ResBlock('Discriminator.3', output)
    output = ResBlock('Discriminator.4', output)
    output = ResBlock('Discriminator.5', output)
    output = tf.reshape(output, [-1, SEQ_LEN*DIM])
    size= 100 #MK add
    output = lib.ops.linear.Linear('Discriminator.reduction', SEQ_LEN*DIM,size, output) #MK change
    output = tf.concat([output,labels],axis=1) #MK add
    output = tf.contrib.layers.fully_connected(output,300,scope='Discriminator.fully',reuse=tf.AUTO_REUSE) #MK add
    output = lib.ops.linear.Linear('Discriminator.output',300 , 1, output) #MK add
    return output

real_inputs_discrete = tf.placeholder(tf.int32, shape=[BATCH_SIZE, SEQ_LEN])
real_inputs = tf.one_hot(real_inputs_discrete, len(charmap))
real_inputs_label = tf.placeholder(tf.float32, shape=[BATCH_SIZE, fold_len]) #MK add
fake_inputs = Generator(BATCH_SIZE,real_inputs_label) #MK change
fake_inputs_discrete = tf.argmax(fake_inputs, fake_inputs.get_shape().ndims-1)

disc_real = Discriminator(real_inputs,real_inputs_label) #MK change 
disc_fake = Discriminator(fake_inputs,real_inputs_label) #MK change

disc_cost = tf.reduce_mean(disc_fake) - tf.reduce_mean(disc_real)
gen_cost = -tf.reduce_mean(disc_fake)

# WGAN lipschitz-penalty
alpha = tf.random_uniform(
    shape=[BATCH_SIZE,1,1], 
    minval=0.,
    maxval=1.
)
differences = fake_inputs - real_inputs
interpolates = real_inputs + (alpha*differences)
gradients = tf.gradients(Discriminator(interpolates,real_inputs_label), [interpolates])[0] #MK change
slopes = tf.sqrt(tf.reduce_sum(tf.square(gradients), reduction_indices=[1,2]))
gradient_penalty = tf.reduce_mean((slopes-1.)**2)

# Dataset iterator
def inf_train_gen(seqs,folds):
    epoch = 0
    while True:
        indices = np.arange(len(seqs),dtype=np.int) #MK add
        #np.random.shuffle(indices) #MK add
        seqs =  [ seqs[i] for i in indices] #MK add
        folds =  [ folds[i] for i in indices] #MK add
        length = len(seqs)-BATCH_SIZE+1
        for i in xrange(0, length, BATCH_SIZE):
            if i + BATCH_SIZE >= length:  #SZ add
                epoch += 1
            yield np.array(    #MK change
                [[charmap[c] for c in l] for l in seqs[i:i+BATCH_SIZE]], 
                dtype='int32'
            ),np.array(
                [l for l in folds[i:i+BATCH_SIZE]], 
                dtype='float32'
            ),epoch #SZ change

def test_train_gen(seqs,folds):
    i = 0
    while True:
        return np.array(    #MK change
                [[charmap[c] for c in l] for l in seqs[i:i+BATCH_SIZE]], 
                dtype='int32'
            ),np.array(
                [l for l in folds[i:i+BATCH_SIZE]], 
                dtype='float32'
            )

check_dic = {}
f_list = os.listdir(check_path+'/')
for f in f_list:
    f = f.split('.')[0].split('_')
    if f[0] == 'model':
        check_dic[f[1]] = f[2]

check_index = sorted([int(i) for i in check_dic.keys()])

print 'Load the index of check points successfully!'

saver  = tf.train.Saver()

with tf.Session() as session:

    session.run(tf.initialize_all_variables())
    
    def generate_samples(label): #MK change
        samples = session.run(fake_inputs,feed_dict={real_inputs_label:label}) #MK change
        samples = np.argmax(samples, axis=2)
        decoded_samples = []
        for i in xrange(len(samples)):
            decoded = []
            for j in xrange(len(samples[i])):
                decoded.append(inv_charmap[samples[i][j]])
            decoded_samples.append(tuple(decoded))
        return decoded_samples
   
    start_time = time.time()
     
    #Identity = []
    #Coverage = []
    #N_alignment = []
    #Padding_Ratio = []

    file_i = open('cWGAN_Validation_Results/Identity_' + test_index,'w')
    file_pad = open('cWGAN_Validation_Results/Padding_Ratio_' + test_index,'w')
    file_i.close()
    file_pad.close()
    
    Check_selected = check_index[49:]
    for c in Check_selected:
        start = time.time()

        saver.restore(session,check_path + "/model_"+str(c)+"_" + check_dic[str(c)] + ".ckpt")
        
        file_i = open('cWGAN_Validation_Results/Identity_' + test_index,'a')
        file_pad = open('cWGAN_Validation_Results/Padding_Ratio_' + test_index,'a')
        file_s = open(sample_path + '/Samples_' + test_index + '_' + str(c),'w')
    
        Ide = []
        Cov = []
        N_al = []
        P_R = []

        for cla in rep_dic.keys():
            l_f = len(rep_dic[cla].keys())
            selected_num = round(l_f/10)
            if selected_num <= 0:
                selected_num += 1
            selected_fold = np.random.choice(rep_dic[cla].keys(),int(selected_num))
            print selected_num
                                
            for f in selected_fold:
                num = 0
                samples_f = []
                padding_num = 0
                while(num < GENERATE_SIZE):
                    f_batch = [folds_dict[f]] * BATCH_SIZE
                    samples = generate_samples(f_batch)
                    samples_strip = [''.join(sam) for sam in samples]
                    for sam in samples_strip:
                        samp = sam.strip('!')
                        if (samp != '') and (not ('!' in samp)):
                            samples_f.append(samp)
                            padding_num += (len(sam) - len(samp))
                            num += 1
                        if num >= GENERATE_SIZE:
                            break
                file_s.write(f + ':\n')
                for s in samples_f:
                    file_s.write(s + '\n')
                file_s.write('\n')
                ide,cov,n_al = Assessment.average_alignment(samples_f,rep_dic[cla][f],matrix)
           
                  
                Ide.append(ide)
                Cov.append(cov)
                N_al.append(n_al)
                P_R.append( float(padding_num) / float(GENERATE_SIZE * SEQ_LEN) )

        ident = np.mean(Ide)
        cover = np.mean(Cov)
        n_alig = np.mean(N_al)
        pad_ratio = np.mean(P_R)

        #Identity.append(ident)
        #Coverage.append(cover)
        #N_alignment.append(n_alig)
        #Padding_Ratio.append(pad_ratio)

        end = time.time()

        file_i.write(str(ident))
        file_i.write('\n')
        file_pad.write(str(pad_ratio))
        file_pad.write('\n')
        file_i.close()
        file_pad.close()

    end_time = time.time()

#print 'Running Time:',end_time - start_time,'s'

"""
plt.figure(1)
plt.plot(Check_selected,Identity) #SZ add
plt.ylim(ymin = 0)
plt.title("Sequence Identity")
plt.ylabel("identity")
plt.xlabel("epoch")
plt.savefig('Images/'+ 'Identity_'+ test_index + '.png')
plt.figure(2)
plt.plot(Check_selected,Coverage) #SZ add
plt.ylim(ymin = 0)
plt.title("Sequence Coverage")
plt.ylabel("coverage")
plt.xlabel("epoch")
plt.savefig('Images/'+ 'Coverage_'+ test_index + '.png')
plt.figure(3)
plt.plot(Check_selected,N_alignment) #SZ add
plt.ylim(ymin = 0)
plt.title("Normalized Alignment Score")
plt.ylabel("normalized alignment score")
plt.xlabel("epoch")
plt.savefig('Images/'+ 'N_alignment_score_'+ test_index + '.png')           
plt.figure(4)
plt.plot(Check_selected,Padding_Ratio) #SZ add
plt.ylim(ymin = 0, ymax = 1)
plt.title("Padding Ratio")
plt.ylabel("padding_ratio")
plt.xlabel("epoch")
plt.savefig('Images/'+ 'Padding_Ratio_Train_'+ test_index + '_from Novelty.png')
plt.show()
"""