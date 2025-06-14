import requests
from requests.auth import HTTPDigestAuth

class CryptoNode:
    def __init__(self, host, port, username, password):
        """
        Initialize the CryptoNode instance with dynamic connection details.
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.url = f"http://{self.host}:{self.port}"

    def _rpc_request(self, method, params=None):
        """
        Make a JSON-RPC request to the connected cryptocurrency node.
        """
        if params is None:
            params = []

        headers = {
            "Content-Type": "application/json"
        }

        payload = {
            "jsonrpc": "1.0",
            "id": "crypto",
            "method": method,
            "params": params
        }

        try:
            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                auth=(self.username, self.password)
            )
            response.raise_for_status()  # Raise HTTP errors
            data = response.json()

            if "error" in data and data["error"] is not None:
                raise Exception(f"RPC Error: {data['error']}")

            return data["result"]

        except requests.exceptions.RequestException as e:
            raise Exception(f"Connection Error: {str(e)}")

    def get_new_address(self):
        """
        Generate a new address for receiving funds.
        """
        return self._rpc_request("getnewaddress")

    def get_block_height(self):
        """
        Get the current block height of the blockchain.
        """
        return self._rpc_request("getblockcount")

    def get_balance_for_address(self, address, minconf=1):
        """
        Get the total amount received by a specific address.
        
        :param address: The address to check the balance for.
        :param minconf: Minimum number of confirmations (default is 1).
        :return: The total amount received by the address.
        """
        return self._rpc_request("getreceivedbyaddress", [address, minconf])


    def send_to_address(self, address, amount):
        """
        Send cryptocurrency to a specified address.
        """
        return self._rpc_request("sendtoaddress", [address, amount, "", "", True])
    
class MoneroNode:
    def __init__(self, host, port, username=None, password=None):
        self.url = f"http://{host}:{port}/json_rpc"
        if username and password:
            self.auth = HTTPDigestAuth(username, password)
        else:
            self.auth = None

    def _rpc(self, method, params=None):
        payload = {
            "jsonrpc": "2.0",
            "id": "0",
            "method": method,
            "params": params or {}
        }
        response = requests.post(self.url, json=payload, auth=self.auth)
        response.raise_for_status()
        data = response.json()
        if 'error' in data:
            raise Exception(f"Monero RPC Error: {data['error']}")
        if 'result' not in data:
            raise Exception(f"Malformed Monero RPC response: {data}")
        return data['result']

    def create_subaddress(self, account_index=0, label=""):
        return self._rpc("create_address", {
            "account_index": account_index,
            "label": label
        })

    def get_transfers(self, account_index=0, subaddr_indices=None, in_=True):
        return self._rpc("get_transfers", {
            "in": in_,
            "account_index": account_index,
            "subaddr_indices": subaddr_indices or []
        })

    def get_balance(self, account_index=0, address_indices=None):
        return self._rpc("get_balance", {
            "account_index": account_index,
            "address_indices": address_indices or []
        })

    def send_to_address(self, address, amount_atomic, subaddr_index=None):
        payload = {
            "destinations": [{"amount": int(amount_atomic), "address": address}],
            "account_index": 0,
            "subtract_fee_from_amount": True,
            "priority": 2  # 0=default, 1=unimportant, 2=normal, etc.
        }

        if subaddr_index is not None:
            payload["subaddr_indices"] = [subaddr_index]

        return self._rpc("transfer", payload)

