# pi
One time installation
```
sudo apt-get install libgpiod2
sudo pip3 install -r requirements.txt
```
Install service
```
cd /etc/systemd/system/
sudo ln -s ~/window/window.service 
sudo systemctl enable window.service
sudo systemctl start window.service
```
Functions
* restart `sudo systemctl restart window.service`.
* view logs `sudo journalctl -f -u window.service`
* follow temperature data `tail -f `date +"%y%m%d"`.csv`