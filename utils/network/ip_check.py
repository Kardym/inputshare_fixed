import ipaddress

def get_ip_from_ip_port(ip_port_str: str) -> str:
    if ip_port_str.count(":") > 1:
        #   IPv6 address
        ip_part = ip_port_str.rsplit(":", 1)[0]
    else: # IPv4 address
        ip_part = ip_port_str.split(":")[0]
    return ip_part

# for only ip address part, like:
# "192.168.2.1"
def is_valid_ip(ip_str: str) -> bool:
    try:
        ipaddress.ip_address(ip_str)
        return True
    except: return False

# for ip + port string, like:
# "192.168.2.1:80"
def is_valid_ip_port(ip_port_str: str) -> bool:
    ip_part = get_ip_from_ip_port(ip_port_str)
    if ip_part == ip_port_str: return False
    return is_valid_ip(ip_part)
