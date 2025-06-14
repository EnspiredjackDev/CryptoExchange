import os
from crypto_node import CryptoNode, MoneroNode 

def get_node(coin_symbol: str):
    coin = coin_symbol.upper()

    host = os.environ.get(f"{coin}_NODE_HOST")
    port = os.environ.get(f"{coin}_NODE_PORT")
    username = os.environ.get(f"{coin}_NODE_USER")
    password = os.environ.get(f"{coin}_NODE_PASS")
    node_type = os.environ.get(f"{coin}_NODE_TYPE", "btc").lower()  # default to BTC-style

    if not all([host, port, username, password]):
        raise Exception(f"Missing credentials for {coin}")

    if node_type == "monero":
        return MoneroNode(host, int(port), username, password)
    else:
        return CryptoNode(host, int(port), username, password)
