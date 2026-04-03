# kf-connect
Helper scripts for connecting to kf resources in amazon

## kfdb 
This is a helper connection script that allows you to define a list of hosts 
in a file that lives inside your home so you can change which host you are 
connecting to based on a simple argument, host.

See the example host file in example-config/example.yaml to learn how to define
the hosts you regularly connect to. 

example usage: 
```bash
kfdb --host d3b --force
```
This will initiate a saml login and then create the tunnel to the host specified 
for d3b. The ports default to standard PGSQL, 5432, however, that can be set in
the kfhosts file (port and local-port can be configured separately if they should
be different)
