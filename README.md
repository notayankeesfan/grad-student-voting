# Election interface

This repository contains Python code for running an election system for MIT graduate students.

# Installation and use

1. Download the software to some location, ideally a Linux server. Point a DNS subdomain at this server.
2. Install the required Python dependencies with `pip install -r requirements.txt`. You may install these inside a virtual environment if you wish.
3. Setup a reverse proxy that points at the Python server. In this repository, this is done using `systemd` and Caddy as the web server. After installing [Caddy](https://caddyserver.com), you can edit your Caddyfile to look like:
```
vote.uenotformit.org {
        reverse_proxy unix//run/gunicorn.sock
}
```
4. Setup a `systemd` service to automatically run the backend service. This can be done by copying the service and socket files in the `systemd` folder to `/etc/systemd/system`, then doing `sudo systemctl daemon-reload` followed by `sudo systemctl enable --now gunicorn.socket`
5. Configure the server settings using environment variables or secret files. By default, this server looks for secret files in the folder `/var/lib/vote-daemon/secrets`. You need to create the following files:

    - `csrf_key`: this protects the forms from replay/other web attacks. You can generate a random key using `openssl rand -base64 25`.
    - `base_url`: this is the URL from which login links are generated. In this case, it is https://vote.uenotformit.org ; it should be changed to your subdomain.
    - `smtp_username`: a MIT kerberos username of the person whose account is responsible for sending the login emails. If you are not part of "UE not for MIT", **you must change the email template in `templates/token_email.txt` and the FROM address on line 113 of `serve.py` to a mailing list you control**.
    - `smtp_password`: the MIT kerberos password used to send the login emails. Protect this secret file!

At this point, Caddy will handle automatically getting HTTPS certificates and starting/communicating with the backend.

## Path notes
Currently, some paths are hard-coded assuming this `systemd`/`caddy` etc setup. If you are running the backend server in a different way, you will likely have to change the sqlite database path (the two strings starting with `sqlite://` in `serve.py` and `__main__.py`) and the secret path file from which credentials are loaded.

# CLI interface

To add/edit/control elections, you can use the basic CLI interface to create, modify, and edit elections. Importantly, elections must be toggled to active before they show up on the website.

For example, an example election can be created with the following:
```
python3 -m vote election add "Test election "2023-05-15" "2023-05-19"
python3 -m vote election list # This shows the election ID number you need for later
python3 -m vote question add 1 "Should a secure voting system be used?" "Yes" "No" # multiple voting questions can be added to an election
python3 -m vote election toggle 1 # This toggles the election from visible to invisible and vice versa
```

You can also use `election remove` and `question remove` to delete elections and questions. You can modify the open/close times of the election using `election open_time` and `election close_time`. For example:
```
python3 -m vote question remove 1
python3 -m election open_time 1 "2023-05-17 23:59:59"
```

# License
This is licensed under the MIT license. You are allowed to use, copy, modify, publish, distribute, sublicense, and sell this software as long as you retain the copyright notice (Copyright 2023 "UE not for MIT" contributors).# grad-student-voting
