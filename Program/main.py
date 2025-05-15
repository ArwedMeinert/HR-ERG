
import tkinter as tk

from GUI import FitnessApp     # assumes GUI.py is next to main.py


def main():
    root = tk.Tk()
    app = FitnessApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
