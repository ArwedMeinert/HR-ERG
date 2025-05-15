import json
import matplotlib.pyplot as plt

def plot_power_and_hr(data_json):
    # Load the JSON data if provided as a string
    if isinstance(data_json, str):
        data = json.loads(data_json)
    else:
        data = data_json  # Assume it's already a dict

    # Extract samples
    samples = data['samples']
    time = [sample['timestamp'] for sample in samples]
    power = [sample['power'] for sample in samples]
    hr = [sample['hr'] for sample in samples]

    # Only extract target_hr if present in all samples
    has_targets = all("target_hr" in s for s in samples)
    if has_targets:
        targets = [s["target_hr"] for s in samples]

    # Create the plot
    fig, ax1 = plt.subplots()

    # Plot power
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Power (W)', color='tab:red')
    ax1.plot(time, power, color='tab:red', label='Power')
    ax1.tick_params(axis='y', labelcolor='tab:red')

    # Create second y-axis for heart rate
    ax2 = ax1.twinx()
    ax2.set_ylabel('Heart Rate (bpm)', color='tab:blue')
    ax2.plot(time, hr, color='tab:blue', label='Heart Rate')

    # Plot target HR if available
    if has_targets:
        ax2.plot(time, targets, color='tab:green', linestyle='--', label='Target HR')

    ax2.tick_params(axis='y', labelcolor='tab:blue')

    # Add title, legend and grid
    plt.title('Power and Heart Rate over Time')
    fig.tight_layout()
    fig.legend(loc='upper left', bbox_to_anchor=(0.1, 0.9))
    plt.grid(True)
    plt.show()

if __name__ == "__main__":
    with open('Workouts_2025-05-14_14-40-02.json') as f:
        data_json = f.read()
        plot_power_and_hr(data_json)
