# coding=utf-8

###############################################################################
################################### Imports ###################################
###############################################################################

import math

import numpy as np
import pandas as pd

from matplotlib import pyplot as plt

import torch
import torch.optim as optim
import torch.nn.functional as F

from replayMemory import ReplayMemory

from Models.UMDQN_C_Model import UMDQN_C_Model
from Models.UMDQN_C_Model_Atari import UMDQN_C_Model_Atari

from DQN import DQN



###############################################################################
################################ Class UMDQN_C ################################
###############################################################################

class UMDQN_C(DQN):
    """
    GOAL: Implementing the UMDQN_C Deep Reinforcement Learning algorithm.
    
    VARIABLES: - device: Hardware specification (CPU or GPU).
               - gamma: Discount factor of the RL algorithm.
               - learningRate: Learning rate of the DL optimizer (ADAM).
               - epsilon: Epsilon value for the DL optimizer (ADAM).
               - targetNetworkUpdate: Update frequency of the target network.
               - learningUpdatePeriod: Frequency of the learning procedure.
               - batchSize: Size of the batch to sample from the replay memory.
               - capacity: Capacity of the replay memory.
               - replayMemory: Experience Replay memory.
               - rewardClipping: Clipping of the RL rewards.
               - gradientClipping: Clipping of the training loss.
               - optimizer: DL optimizer (ADAM).
               - epsilonStart: Initial value of epsilon (Epsilon-Greedy).
               - epsilonEnd: Final value of epsilon (Epsilon-Greedy).
               - epsilonDecay: Exponential decay of epsilon (Epsilon-Greedy).
               - epsilonTest: Test value of epsilon (Epsilon-Greedy).
               - epsilonValue: Current value of epsilon (Epsilon-Greedy).
               - policyNetwork: Deep Neural Network representing the info used by the RL policy.
               - targetNetwork: Deep Neural Network representing the target network.
                                
    METHODS: - __init__: Initialization of the RL algorithm.
             - chooseAction: Choose a valid action based on the current state
                             observed, according to the RL policy learned.
             - learning: Execute the RL algorithm learning procedure.
    """

    def __init__(self, observationSpace, actionSpace, environment,
                 parametersFileName='', reporting=True):
        """
        GOAL: Initializing the RL agent based on the UMDQN_C Deep Reinforcement Learning
              algorithm, by setting up the algorithm parameters as well as 
              the Deep Neural Networks.
        
        INPUTS: - observationSpace: RL observation space.
                - actionSpace: RL action space.
                - environment: Name of the RL environment.
                - parametersFileName: Name of the JSON parameters file.
                - reporting: Enable the reporting of the results.
        
        OUTPUTS: /
        """

        # Initialization of the DQN parent class
        DQN.__init__(self, observationSpace, actionSpace, environment, parametersFileName, False)

        # Setting of the parameters
        if parametersFileName == '':
            parametersFileName = ''.join(['Parameters_parameters_UMDQN_C_', str(environment), '.json'])
        parameters = self.readParameters(parametersFileName)

        # Set the device for DNN computations (CPU or GPU)
        self.device = torch.device('cuda:'+str(parameters['GPUNumber']) if torch.cuda.is_available() else 'cpu')

        # Set the general parameters of the RL algorithm
        self.gamma = parameters['gamma']
        self.learningRate = parameters['learningRate']
        self.epsilon = parameters['epsilon']
        self.targetUpdatePeriod = parameters['targetUpdatePeriod']
        self.learningUpdatePeriod = parameters['learningUpdatePeriod']
        self.rewardClipping = parameters['rewardClipping']
        self.gradientClipping = parameters['gradientClipping']

        # Set the Experience Replay mechanism
        self.batchSize = parameters['batchSize']
        self.capacity = parameters['capacity']
        self.replayMemory = ReplayMemory(self.capacity)

        # Set the distribution support
        self.numberOfSamples = parameters['numberOfSamples']
        self.minReturn = parameters['minReturn']
        self.maxReturn = parameters['maxReturn']
        self.support = np.linspace(self.minReturn, self.maxReturn, self.numberOfSamples)
        self.supportTorch = torch.linspace(self.minReturn, self.maxReturn, self.numberOfSamples, device=self.device)
        self.supportRepeatedBatchSize = self.supportTorch.repeat(self.batchSize, 1).view(-1, 1)
        self.uniformProba = 1/(self.maxReturn - self.minReturn)

        # Enable the faster but potentially less accurate estimation of the expectation
        self.fasterExpectation = parameters['fasterExpectation']

        # Set the two Deep Neural Networks of the RL algorithm (policy and target)
        self.atari = parameters['atari']
        self.minatar = parameters['minatar']
        if self.atari or self.minatar:
            self.policyNetwork = UMDQN_C_Model_Atari(observationSpace, actionSpace, parameters['structureUMNN'], parameters['stateEmbedding'], parameters['numberOfSteps'], self.device, minAtar=self.minatar).to(self.device)
            self.targetNetwork = UMDQN_C_Model_Atari(observationSpace, actionSpace, parameters['structureUMNN'], parameters['stateEmbedding'], parameters['numberOfSteps'], self.device, minAtar=self.minatar).to(self.device)
        else:
            self.policyNetwork = UMDQN_C_Model(observationSpace, actionSpace, parameters['structureDNN'], parameters['structureUMNN'], parameters['stateEmbedding'], parameters['numberOfSteps'], self.device).to(self.device)
            self.targetNetwork = UMDQN_C_Model(observationSpace, actionSpace, parameters['structureDNN'], parameters['structureUMNN'], parameters['stateEmbedding'], parameters['numberOfSteps'], self.device).to(self.device)
        self.targetNetwork.load_state_dict(self.policyNetwork.state_dict())

        # Set the Deep Learning optimizer
        self.optimizer = optim.Adam(self.policyNetwork.parameters(), lr=self.learningRate, eps=self.epsilon)

        # Set the Epsilon-Greedy exploration technique
        self.epsilonStart = parameters['epsilonStart']
        self.epsilonEnd = parameters['epsilonEnd']
        self.epsilonDecay = parameters['epsilonDecay']
        self.epsilonTest = parameters['epsilonTest']
        self.epsilonValue = lambda iteration: self.epsilonEnd + (self.epsilonStart - self.epsilonEnd) * math.exp(-1 * iteration / self.epsilonDecay)

        # Initialization of the experiment folder and tensorboard writer
        self.initReporting(parameters, 'UMDQN_C')


    def chooseAction(self, state, plot=False):
        """
        GOAL: Choose a valid RL action from the action space according to the
              RL policy as well as the current RL state observed.
        
        INPUTS: - state: RL state returned by the environment.
                - plot: Enable the plotting of the random returns distributions.
        
        OUTPUTS: - action: RL action chosen from the action space.
        """

        # Choose the best action based on the RL policy
        with torch.no_grad():
            state = torch.from_numpy(state).float().to(self.device).unsqueeze(0)
            if self.fasterExpectation:
                QValues = self.policyNetwork.getExpectation(state, self.minReturn, self.maxReturn, 10*self.numberOfSamples).squeeze(0)
            else:
                pdfs = self.policyNetwork.getDerivative(state, self.supportTorch.unsqueeze(1))
                QValues = (pdfs * self.supportTorch).sum(1)/(self.numberOfSamples*self.uniformProba)
            _, action = QValues.max(0)

            # If required, plot the return distribution associated with each action
            #plot = (int(state[0][0]) == int(7/2)-1 and int(state[0][1]) ==  7-1)
            if plot:
                colors = ['blue', 'red', 'orange', 'green', 'purple', 'brown']
                plt.figure()
                ax1 = plt.subplot(2, 1, 1)
                ax2 = plt.subplot(2, 1, 2)
                with torch.no_grad():
                    accurateSupport = np.linspace(self.minReturn, self.maxReturn, self.numberOfSamples*10)
                    accurateSupportTorch = torch.linspace(self.minReturn, self.maxReturn, self.numberOfSamples*10, device=self.device)
                    cdfs = self.policyNetwork(state, accurateSupportTorch.unsqueeze(1))
                    pdfs = self.policyNetwork.getDerivative(state, accurateSupportTorch.unsqueeze(1))
                    QValues = ((pdfs * accurateSupportTorch).sum(1))/(self.numberOfSamples*10*self.uniformProba)
                for a in range(self.actionSpace):
                    ax1.plot(accurateSupport, cdfs[a].cpu(), linestyle='-', label=''.join(['Action ', str(a), ' random return Z']), color=colors[a])
                    ax2.plot(accurateSupport, pdfs[a].cpu(), linestyle='-', label=''.join(['Action ', str(a), ' random return Z']), color=colors[a])
                    ax2.fill_between(accurateSupport, accurateSupport*0, pdfs[a].cpu(), alpha=0.25, color=colors[a])
                    ax1.axvline(x=QValues[a], linewidth=2, linestyle='--', label=''.join(['Action ', str(a), ' expected return Q']), color=colors[a])
                    ax2.axvline(x=QValues[a], linewidth=2, linestyle='--', label=''.join(['Action ', str(a), ' expected return Q']), color=colors[a])
                ax1.set_xlabel('Random return')
                ax1.set_ylabel('Cumulative Density Function (CDF)')
                ax2.set_xlabel('Random return')
                ax2.set_ylabel('Probability Density Function (PDF)')
                ax1.legend()
                ax2.legend()
                plt.show()
                #"""
                # Saving of the data into external files
                dataCDF = {
                'Action0_x': accurateSupport,
                'Action0_y': cdfs[0].cpu(),
                'Action1_x': accurateSupport,
                'Action1_y': cdfs[1].cpu(),
                'Action2_x': accurateSupport,
                'Action2_y': cdfs[2].cpu(),
                'Action3_x': accurateSupport,
                'Action3_y': cdfs[3].cpu(),
                }
                dataframeCDF = pd.DataFrame(dataCDF)
                dataframeCDF.to_csv('Figures/Distributions/UMDQN_C.csv')
                quit()
                #"""
        
            return action.item()


    def learning(self):
        """
        GOAL: Sample a batch of past experiences and learn from it
              by updating the Reinforcement Learning policy.
        
        INPUTS: /
        
        OUTPUTS: - loss: Loss of the learning procedure.
        """
        
        # Check that the replay memory is filled enough
        if (len(self.replayMemory) >= self.batchSize):
            
            # Sample a batch of experiences from the replay memory
            batch = next(self.dataLoaderIter)
            state = batch[0].float().to(self.device)
            action = batch[1].float().to(self.device)
            reward = batch[2].float().to(self.device)
            nextState = batch[3].float().to(self.device)
            done = batch[4].float().to(self.device)

            # Computation of the current return distribution, according to the policy DNN
            cdfs = self.policyNetwork(state, self.supportRepeatedBatchSize)
            selection = torch.tensor(np.array([self.actionSpace*i + action[i] for i in range(self.batchSize)]), dtype=torch.long, device=self.device)
            cdfs = torch.index_select(cdfs, 0, selection).view(-1, 1)

            # Computation of the next action, according to the policy DNN
            if self.fasterExpectation:
                expectedReturns = self.targetNetwork.getExpectation(nextState, self.minReturn, self.maxReturn, 10*self.numberOfSamples)
            else:
                pdfs = self.targetNetwork.getDerivative(nextState, self.supportRepeatedBatchSize)
                expectedReturns = (((pdfs * self.supportTorch).sum(1))/(self.numberOfSamples*self.uniformProba)).view(-1, self.actionSpace)
            _, nextAction = expectedReturns.max(1)

            # Computation of the new distribution to be learnt by the policy DNN
            with torch.no_grad():
                r = reward.view(self.batchSize, 1).repeat(1, self.numberOfSamples).view(-1, 1)
                support = (self.supportRepeatedBatchSize - r)/self.gamma
                targetCdfs = self.targetNetwork(nextState, support)
                selection = torch.tensor([self.actionSpace*i + nextAction[i] for i in range(self.batchSize)], dtype=torch.long, device=self.device)
                targetCdfs = torch.index_select(targetCdfs, 0, selection)
                for i in range(self.batchSize):
                    if done[i] == 1:
                        targetCdfs[i] = (self.supportTorch > reward[i]).float() 
                targetCdfs = targetCdfs.view(-1, 1)
            
            # Compute the loss
            loss = F.mse_loss(cdfs, targetCdfs)

            # Computation of the gradients
            self.optimizer.zero_grad()
            loss.backward()

            # Gradient Clipping
            torch.nn.utils.clip_grad_norm_(self.policyNetwork.parameters(), self.gradientClipping)

            # Perform the Deep Neural Network optimization
            self.optimizer.step()

            return loss.item()
