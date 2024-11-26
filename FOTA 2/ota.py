import network
import urequests
import os
import json
import machine
from time import sleep
import logging

class OTAUpdater:
    """ This class handles OTA updates. It connects to the Wi-Fi, checks for updates, downloads and installs them."""
    def __init__(self, repo_url, filename):
        self.filename = filename
        self.repo_url = repo_url
        if "www.github.com" in self.repo_url :
            logging.debug(f"> Updating {repo_url} to raw.githubusercontent")
            self.repo_url = self.repo_url.replace("www.github","raw.githubusercontent")
        elif "github.com" in self.repo_url:
            logging.debug(f"> Updating {repo_url} to raw.githubusercontent")
            self.repo_url = self.repo_url.replace("github","raw.githubusercontent")            
        self.version_url = self.repo_url + 'main/version.json'
        logging.debug(f"> Version url is: {self.version_url}")
        self.firmware_url = self.repo_url + 'main/' + filename

        # get the current version (stored in version.json)
        if 'version.json' in os.listdir():    
            with open('version.json') as f:
                self.current_version = int(json.load(f)['version'])
            logging.debug(f"> Current device firmware version is {self.current_version}")

        else:
            self.current_version = 0
            # save the current version
            with open('version.json', 'w') as f:
                json.dump({'version': self.current_version}, f)
            
    def fetch_latest_code(self)->bool:
        """ Fetch the latest code from the repo, returns False if not found."""
        
        # Fetch the latest code from the repo.
        response = urequests.get(self.firmware_url)
        if response.status_code == 200:
            logging.debug(f'> Fetched latest firmware code, status: {response.status_code}')
    
            # Save the fetched code to memory
            self.latest_code = response.text
            return True
        
        elif response.status_code == 404:
            logging.error(f'> Firmware not found - {self.firmware_url}.')
            return False

    def update_no_reset(self):
        """ Update the code without resetting the device."""

        # Save the fetched code and update the version file to latest version.
        with open('latest_code.py', 'w') as f:
            f.write(self.latest_code)
        
        # update the version in memory
        self.current_version = self.latest_version

        # save the current version
        with open('version.json', 'w') as f:
            json.dump({'version': self.current_version}, f)
        
        # free up some memory
        self.latest_code = None

        # Overwrite the old code.
#         os.rename('latest_code.py', self.filename)

    def update_and_reset(self):
        """ Update the code and reset the device."""

        logging.debug(f"> Updating device... (Renaming latest_code.py to {self.filename})", end="")

        # Overwrite the old code.
        os.rename('latest_code.py', self.filename)  

        # Restart the device to run the new code.
        logging.debug('> Restarting device...')
        machine.reset()  # Reset the device to run the new code.
        
    def check_for_updates(self):
        """ Check if updates are available."""
        
        logging.debug(f'> Checking for latest version... on {self.version_url}')
        response = urequests.get(self.version_url)
        
        data = json.loads(response.text)
        
        logging.debug(f"> Data is: {data}, url is: {self.version_url}")
        # Turn list to dict using dictionary comprehension
#         my_dict = {data[i]: data[i + 1] for i in range(0, len(data), 2)}
        
        self.latest_version = int(data['version'])
        logging.debug(f'> Latest version is: {self.latest_version}')
        
        # compare versions
        self.newer_version_available = True if self.current_version < self.latest_version else False
        
        logging.debug(f'> Newer version available: {self.newer_version_available}')    
        return self.newer_version_available
    
    def download_and_install_update_if_available(self):
        """ Check for updates, download and install them."""
        if self.check_for_updates():
            if self.fetch_latest_code():
                self.update_no_reset() 
                self.update_and_reset() 
        else:
            logging.debug(f'> No new updates available.')
