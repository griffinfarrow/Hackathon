import gym
import matplotlib.pyplot as plt
import numpy as np


def get_mode(arr, bin_number=10):
    arr = arr[~np.isnan(arr)]  # ~ means not

    if len(arr) > 0:
        hist, bin_edges = np.histogram(arr, bins=bin_number)
        centers = 0.5 * (bin_edges[1:] + bin_edges[:-1])
        max_idx = np.argmax(hist)
        mode = centers[max_idx]
        return mode
    else:
        # print('Just nans')
        return np.nan


def get_expected_price(price_array, idx, window_size=2 * 24, mode="mode"):
    idx = int(idx)

    if idx == 0:
        arr = price_array[idx]
    elif idx < window_size:
        arr = price_array[:idx]
    else:
        arr = price_array[idx - window_size : idx]

    if mode == "mean":
        return np.mean(arr)
    if mode == "mode":
        return get_mode(arr, 5)
    if mode == "median":
        return np.median(arr)


class energy_price_env(gym.Env):
    def __init__(self, obs_price_array, start_energy=1, window_size=1000, power=1):
        self.price_array = obs_price_array
        self.action_space = gym.spaces.Discrete(3)
        # current_price, mean_price, current_energy, time
        self.observation_space = gym.spaces.Box(
            low=np.array([-np.inf, -np.inf, 0, 0]),
            high=np.array([np.inf, np.inf, 1, np.inf]),
            dtype=np.float32,
        )
        # our state is the charge
        self.start_energy = start_energy
        self.window_size = window_size

        self.time = 0
        self.earnings = 0
        self.power = power  # MW
        self.capacity = 1  # MWh
        self.efficiency = 0.85

        self.state = np.array(
            [
                self.get_price(self.time),
                self.get_expected_price(self.time),
                start_energy,
            ]
        )

    def get_state(self):
        return self.state

    def get_price(self, idx):
        return self.price_array[int(idx)]

    def get_expected_price(self, idx, window_size=2 * 24, mode="median"):
        return get_expected_price(
            self.price_array, idx, window_size=window_size, mode=mode
        )

    def step(self, action):
        current_price, mean_price, current_energy, current_time = self.state
        mapped_action = env2human(action)
        if mapped_action == -1:
            # discharge === selling for 30 mins
            new_energy = current_energy - (self.power * 0.5)

        elif mapped_action == 0:
            # hold === do nothing
            new_energy = current_energy
        elif mapped_action == 1:
            # charge === buy energy for 30 mins
            new_energy = current_energy + (self.power * 0.5 * self.efficiency)

        # make sure energy cannot be greater than capacity
        new_energy = max(0, new_energy)
        new_energy = min(self.capacity, new_energy)
        # now work out the delta energy
        delta_energy = new_energy - current_energy

        revenue = -delta_energy * current_price
        self.earnings += revenue
        expected_profit = -delta_energy * mean_price

        opportunity_cost = revenue - expected_profit

        reward = opportunity_cost  # profit * multiplier * price_diff_from_expected

        # print("Delta energy: ", delta_energy)
        # print("Price diff from expected: ", price_diff_from_expected)
        # print("Revenue: ", revenue)
        # print("Expected Profit: ", expected_profit)
        # print("Reward ", reward)

        # increase the time
        current_time += 1

        self.state = (
            self.get_price(current_time),
            self.get_expected_price(current_time),
            new_energy,
            current_time,
        )

        info = {}
        # end when we run out of data
        if current_time >= self.price_array.shape[0] - 1:
            done = True
        else:
            done = False

        return np.array(self.state), reward, done, info

    def reset(self):
        # this resets the environment so it can try again
        # print('Environment reset')
        self.time = 0
        self.state = np.array(
            [
                self.get_price(self.time),
                self.get_expected_price(self.time),
                self.start_energy,
                self.time,
            ]
        )
        # ! this puts us at the start of the week, we could make this random?
        self.earnings = 0
        return self.state


def humans2env(action):
    return int(action + 1)


def env2human(action):
    return int(action - 1)


def evaluate(model, new_env=None, num_episodes=100, index=None):
    """
    Evaluate a RL agent
    :param model: (BaseRLModel object) the RL Agent
    :param num_episodes: (int) number of episodes to evaluate it
    :return: (float) Mean reward for the last num_episodes
    """
    # This function will only work for a single Environment
    if new_env is None:
        env = model.get_env()
    else:
        env = new_env
    env.reset()
    all_episode_rewards = []

    for i in range(num_episodes):

        episode_rewards = []

        if i == 0:
            current_prices = []
            mean_prices = []
            current_energies = []
            all_earnings = [0]
            current_times = []

        done = False
        obs = env.reset()
        while not done:
            # _states are only useful when using LSTM policies
            action, _states = model.predict(obs)
            # here, action, rewards and dones are arrays
            # because we are using vectorized env
            obs, reward, done, info = env.step(action)
            current_price, mean_price, current_energy, current_time = (
                obs[0, 0],
                obs[0, 1],
                obs[0, 2],
                obs[0, 3],
            )
            episode_rewards.append(reward)

            if i == 0:
                if len(current_energies) > 0:
                    all_earnings.append(
                        -current_price * (current_energy - current_energies[-1])
                    )

                current_prices.append(current_price)
                mean_prices.append(mean_price)
                current_energies.append(current_energy)
                current_times.append(current_time)

        all_episode_rewards.append(sum(episode_rewards))

    fig, axs = plt.subplots(4, 1, sharex=True, figsize=(20, 15))
    if index is None:
        index = np.arange(0, len(current_times))[:-1]
    else:
        index = index[np.asarray(current_times, dtype=int)][:-1]
    cum_rewards = np.cumsum(episode_rewards)
    bank_total = np.cumsum(all_earnings)
    axs[0].plot(index, cum_rewards[:-1], color="red", label="Cumalative rewards")
    axs[0].plot(index, bank_total[:-1], color="blue", label="Bank total")
    axs[0].legend(loc="upper left")
    axs[1].plot(index, current_prices[:-1], color="blue", label="Current prices")
    axs[1].plot(index, mean_prices[:-1], color="red", label="Mean prices")
    axs[1].legend(loc="upper left")

    axs[2].plot(index, episode_rewards[:-1], color="black", label="Reward")
    # axs[2].legend()

    axs[3].plot(index, current_energies[:-1], color="blue", label="Current energies")
    fig.autofmt_xdate()
    mean_episode_reward = np.mean(all_episode_rewards)
    std_episode_reward = np.std(all_episode_rewards)

    axs[0].set_ylabel("Price")
    axs[1].set_ylabel("Price")
    axs[2].set_ylabel("Reward")
    axs[3].set_ylabel("Current Energy")

    print(
        "Mean reward:",
        mean_episode_reward,
        "+/-",
        std_episode_reward,
        "\t Num episodes:",
        num_episodes,
    )

    return mean_episode_reward


def quick_eval(model):
    """
    Evaluation func for the multiprocessing that we have designed to be as quick as possible!
    """
    print("called")
    env = model.get_env()
    env.reset()
    done = False
    episode_rewards = []
    obs = env.reset()
    while not done:
        action, _states = model.predict(obs)
        obs, reward, done, info = env.step(action)
        episode_rewards.append(reward)
    return sum(episode_rewards)
