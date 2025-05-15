
import tkinter as tk

from GUI import FitnessApp     # assumes GUI.py is next to main.py


def main():
    root = tk.Tk()
    # Pass the config path into your app if you want:
    app = FitnessApp(root)
    # e.g. app.load_config(args.config)  <-- you could extend your class to accept a path
    root.mainloop()

if __name__ == "__main__":
    main()
