import requests

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
        return self._rpc_request("sendtoaddress", [address, amount])
