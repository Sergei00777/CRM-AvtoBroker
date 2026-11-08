"""Точка входа для PyCharm: Shift+F10 запускает CRM АвтоБрокер (то же самое, что python app.py)."""
import os
import runpy
import sys

if __name__ == "__main__":
    sys.argv = ["app.py", *sys.argv[1:]]
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), run_name="__main__")
