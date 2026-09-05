"""
Solana devnet client for ReliefTrace. One Memo-program transaction per relief
delivery, signed by a local devnet keypair funded from the public faucet.
Devnet only - never real funds.

Shared by:
  - main.py            (POST /api/contribute: one memo per submitted contribution)
  - solana_deliveries.py (batch-anchor synthetic deliveries missing a signature)

The wallet lives in keys/wallet.json (git-ignored). If it's absent we seed it
from the keypair recorded in keys/solana_donation_address.md so the address
matches what the frontend advertises; failing that we generate a fresh one.
"""

import json
import os
import re

from dotenv import load_dotenv
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

load_dotenv()

KEYS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "keys"))
WALLET_PATH = os.path.join(KEYS_DIR, "wallet.json")
SEED_KEYPAIR_DOC = os.path.join(KEYS_DIR, "solana_donation_address.md")

DEVNET_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
MEMO_PROGRAM_ID = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")

MIN_BALANCE_LAMPORTS = 50_000_000    # ~0.05 SOL; a memo tx costs 5000 lamports
AIRDROP_LAMPORTS = 1_000_000_000     # 1 SOL - devnet faucet per-request cap

_client: Client | None = None
_wallet: Keypair | None = None


def _seed_secret_from_doc() -> list[int] | None:
    """Pull the '[n, n, ...]' secret-key array out of solana_donation_address.md."""
    try:
        with open(SEED_KEYPAIR_DOC) as f:
            text = f.read()
    except OSError:
        return None
    match = re.search(r"\[([\d,\s]+)\]", text)
    if not match:
        return None
    nums = [int(n) for n in match.group(1).split(",") if n.strip()]
    return nums if len(nums) == 64 else None


def _secret_from_env() -> list[int] | None:
    """SOLANA_WALLET_SECRET: the 64-int secret-key array as JSON, for hosts
    where keys/ isn't deployed."""
    raw = os.getenv("SOLANA_WALLET_SECRET", "").strip()
    if not raw:
        return None
    nums = json.loads(raw)
    if not isinstance(nums, list) or len(nums) != 64:
        raise ValueError("SOLANA_WALLET_SECRET must be a JSON array of 64 ints")
    return [int(n) for n in nums]


def load_or_create_wallet() -> Keypair:
    # 1. explicit env secret (deployed hosts)
    env_secret = _secret_from_env()
    if env_secret is not None:
        return Keypair.from_bytes(bytes(env_secret))

    # 2. local wallet file
    os.makedirs(KEYS_DIR, exist_ok=True)
    if os.path.exists(WALLET_PATH):
        with open(WALLET_PATH) as f:
            return Keypair.from_bytes(bytes(json.load(f)))

    # 3. seed from the committed-locally keypair doc, else generate a fresh one
    secret = _seed_secret_from_doc()
    keypair = Keypair.from_bytes(bytes(secret)) if secret else Keypair()
    with open(WALLET_PATH, "w") as f:
        json.dump(list(bytes(keypair)), f)
    print(f"Wrote devnet wallet {keypair.pubkey()} -> {WALLET_PATH}")
    return keypair


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(DEVNET_URL)
    return _client


def get_wallet() -> Keypair:
    global _wallet
    if _wallet is None:
        _wallet = load_or_create_wallet()
    return _wallet


class WalletNotFunded(RuntimeError):
    pass


def ensure_funded(min_lamports: int = MIN_BALANCE_LAMPORTS) -> int:
    """Top up from the devnet faucet if the balance is low. Returns the balance.
    Raises WalletNotFunded with actionable text if the wallet still has nothing
    (the public RPC faucet is frequently rate-limited per IP)."""
    client, wallet = get_client(), get_wallet()
    balance = client.get_balance(wallet.pubkey()).value
    if balance >= min_lamports:
        return balance
    try:
        sig = client.request_airdrop(wallet.pubkey(), AIRDROP_LAMPORTS).value
        client.confirm_transaction(sig, commitment=Confirmed)
        balance = client.get_balance(wallet.pubkey()).value
    except Exception as exc:  # faucet is rate-limited per IP/address
        print(f"devnet airdrop failed ({exc})")

    if balance == 0:
        addr = wallet.pubkey()
        raise WalletNotFunded(
            f"devnet wallet {addr} has 0 SOL and the RPC faucet is rate-limiting airdrops. "
            f"Fund it once, then retry: `solana airdrop 2 {addr} --url devnet` "
            f"or paste the address at https://faucet.solana.com (select devnet)."
        )
    return balance


def send_memo(memo_text: str) -> str:
    """Send one Memo-program transaction on devnet. Returns the confirmed signature."""
    client, wallet = get_client(), get_wallet()
    ix = Instruction(
        program_id=MEMO_PROGRAM_ID,
        accounts=[AccountMeta(pubkey=wallet.pubkey(), is_signer=True, is_writable=True)],
        data=memo_text.encode("utf-8"),
    )
    blockhash: Hash = client.get_latest_blockhash().value.blockhash
    msg = Message.new_with_blockhash([ix], wallet.pubkey(), blockhash)
    tx = Transaction([wallet], msg, blockhash)
    # send the solders-signed tx as raw bytes; the higher-level
    # send_transaction wrapper expects a legacy solana-py Transaction.
    resp = client.send_raw_transaction(
        bytes(tx), opts=TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
    )
    client.confirm_transaction(resp.value, commitment=Confirmed)
    return str(resp.value)


def build_memo(*, donor: str, resource: str, zone: str, quantity: float) -> str:
    return (
        f"ReliefTrace|zone={zone}|resource={resource}"
        f"|qty={quantity:g}|donor={donor}"
    )


if __name__ == "__main__":
    w = get_wallet()
    bal = ensure_funded()
    print(f"Wallet {w.pubkey()} balance: {bal / 1e9:.4f} SOL")
    demo = send_memo(build_memo(donor="ReliefTrace Self-Test", resource="Water", zone="Test Zone", quantity=1))
    print(f"Test memo tx: https://explorer.solana.com/tx/{demo}?cluster=devnet")
