import os
import tricks as t
t.set_path()
from res import constants as c

def print_status():
    print(f"{t.YELLOW}\n## Current status ##\n{t.RESET}")

    backup_info = t.load_from_json(c.BACKUP_INFO)

    print(f"Number of categories: {backup_info['numberOfCategories']}")
    print(f"Number of channels: {backup_info['numberOfChannels']}")

    print(f"Last exported: {backup_info['dates']['exportedAt']}")

def print_main_menu():
    
    print(f"{t.YELLOW}\n# Socrates main menu #\n{t.RESET}")
    print("Select an option:")

    print("  1. Current status")
    print("  2. Configuration")
    print("  3. Run the pipeline")

    print("  4. Exit\n")

def main():

    while True:

        print_main_menu()
        choice = input("Select an option: ")

        if choice == "1":
            print_status()
            input("\nPress Enter to continue...\n")

        elif choice == "2":
            print("Configuration")

        elif choice == "3":
            print("Run the pipeline")

        elif choice == "4":
            break

        else:
            print("Invalid choice. Please try again.\n")

    print(f"{t.YELLOW}\n# Until we meet again... #\n{t.RESET}")

if __name__ == "__main__": main()