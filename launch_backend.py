from huggingface_hub import HfApi
import os

TOKEN = os.environ.get("DEBUG")

API = HfApi(token=TOKEN)
def start_space():
    API.pause_space("EnergyStarAI/backend_test")
    API.restart_space("EnergyStarAI/backend_test")

if __name__ == "__main__":
  start_space()
