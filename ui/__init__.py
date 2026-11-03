import customtkinter as ctk

from utils import script_abs_path
from utils.config_manager import get_config

script_path = script_abs_path(__file__)
ICON_ICO_PATH = script_path.joinpath("./icon.ico")
ICON_PNG_PATH = script_path.joinpath("./icon.png")

ctk.set_appearance_mode(get_config().theme)
