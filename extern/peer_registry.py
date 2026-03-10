"""
StructurePulse — Peer Registry
Manages known peers for meta-library network participation.

Phase 4a (now):   file-system peers — sibling repos on same machine
Phase 4b (future): HTTP peers — REST endpoint per repo
Phase 4c (future): federated index — opt-in public registry

Design constraint: the peer interface is identical regardless of transport.
Adding HTTP support = implement _fetch_http() with same return signature.
"""
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


PEER_FILE = ".structurepulse/peers.json"


@dataclass
class Peer:
    id: str                       # unique peer id
    name: str                     # human name
    transport: str                # "file" | "http" (future)
    address: str                  # file path OR http URL
    trust_level: str = "low"      # low | medium | high
    min_shi: float = 0.65         # minimum SHI to accept from this peer
    tags_filter: list = field(default_factory=list)  # only accept these tags
    last_sync: str = ""
    last_bundle: str = ""         # path of most recently fetched bundle
    sync_count: int = 0
    added_at: str = ""
    active: bool = True


class PeerRegistry:
    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root)
        self.peer_file = self.root / PEER_FILE

    def ensure_dir(self):
        (self.root / ".structurepulse").mkdir(exist_ok=True)

    # ── CRUD ──────────────────────────────────────────────────────────────
    def add(self, name: str, address: str,
            transport: str = "file",
            trust_level: str = "low",
            min_shi: float = 0.65,
            tags_filter: list = None) -> Peer:
        peers = self.read_all()
        # deduplicate by address
        for p in peers:
            if p.address == address:
                return p

        peer = Peer(
            id=f"peer-{len(peers)+1:04d}",
            name=name,
            transport=transport,
            address=address,
            trust_level=trust_level,
            min_shi=min_shi,
            tags_filter=tags_filter or [],
            added_at=datetime.now(timezone.utc).isoformat(),
        )
        peers.append(peer)
        self._write(peers)
        return peer

    def remove(self, peer_id: str) -> bool:
        peers = self.read_all()
        before = len(peers)
        peers = [p for p in peers if p.id != peer_id]
        self._write(peers)
        return len(peers) < before

    def get(self, peer_id: str) -> Optional[Peer]:
        for p in self.read_all():
            if p.id == peer_id:
                return p
        return None

    def read_all(self, active_only: bool = False) -> list[Peer]:
        if not self.peer_file.exists():
            return []
        data = json.loads(self.peer_file.read_text(encoding="utf-8"))
        peers = [Peer(**p) for p in data.get("peers", [])]
        if active_only:
            peers = [p for p in peers if p.active]
        return peers

    def _write(self, peers: list[Peer]):
        self.ensure_dir()
        self.peer_file.write_text(
            json.dumps({"peers": [asdict(p) for p in peers]}, indent=2),
            encoding="utf-8"
        )

    # ── FETCH ─────────────────────────────────────────────────────────────
    def fetch_bundle(self, peer: Peer, output_dir: str) -> str:
        """
        Fetch the latest bundle from a peer.
        Returns local path to the downloaded bundle.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        if peer.transport == "file":
            return self._fetch_file(peer, out)
        elif peer.transport == "http":
            return self._fetch_http(peer, out)
        else:
            raise ValueError(f"Unknown transport: {peer.transport}")

    def _fetch_file(self, peer: Peer, output_dir: Path) -> str:
        """
        File transport: peer.address is either:
        - a direct .sptgz file path, OR
        - a workspace root (we look for .structurepulse/export.sptgz)
        """
        addr = Path(peer.address)

        if addr.suffix in (".gz", ".sptgz") and addr.is_file():
            bundle_src = addr
        else:
            # workspace root — look for exported bundle
            bundle_src = addr / ".structurepulse" / "export.sptgz"
            if not bundle_src.exists():
                raise FileNotFoundError(
                    f"No bundle at {bundle_src}. "
                    f"Run 'structurepulse network export' in the peer repo first."
                )

        # copy to local output dir
        dest = output_dir / f"{peer.id}_{bundle_src.name}"
        import shutil
        shutil.copy2(bundle_src, dest)

        # update peer record
        self._update_peer(peer.id, last_sync=datetime.now(timezone.utc).isoformat(),
                          last_bundle=str(dest))
        return str(dest)

    def _fetch_http(self, peer: Peer, output_dir: Path) -> str:
        """
        HTTP transport — fetch bundle from a remote StructurePulse server.
        Calls: GET {peer.address}/api/bundle?min_shi={peer.min_shi}
        Returns path to the downloaded bundle file.
        """
        import urllib.request
        import urllib.error

        url = f"{peer.address.rstrip('/')}/api/bundle?min_shi={peer.min_shi}"
        output_path = output_dir / f"{peer.id}_remote.sptgz"

        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"HTTP {resp.status} from {peer.name} ({url})"
                    )
                data = resp.read()
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot reach peer '{peer.name}' at {peer.address}: {e.reason}"
            ) from e

        output_path.write_bytes(data)
        return str(output_path)

    def _update_peer(self, peer_id: str, **kwargs):
        peers = self.read_all()
        for p in peers:
            if p.id == peer_id:
                for k, v in kwargs.items():
                    if hasattr(p, k):
                        setattr(p, k, v)
                p.sync_count += 1
        self._write(peers)

    # ── AUTO-EXPORT ───────────────────────────────────────────────────────
    def auto_export(self, library, shi_threshold: float = 0.65,
                    repo_fingerprint: str = "") -> str:
        """
        Build and write export.sptgz to .structurepulse/.
        Called automatically on install-hook or by cron.
        Returns path to written bundle.
        """
        from structurepulse.network.bundle import BundleBuilder
        self.ensure_dir()
        out_path = self.root / ".structurepulse" / "export.sptgz"
        builder = BundleBuilder()
        builder.build(
            library=library,
            output_path=str(out_path),
            shi_threshold=shi_threshold,
            repo_fingerprint=repo_fingerprint,
        )
        return str(out_path)


def format_peers_cli(peers: list[Peer]) -> str:
    if not peers:
        return "  (no peers registered)"
    lines = []
    for p in peers:
        status = "active" if p.active else "inactive"
        last = p.last_sync[:16].replace("T", " ") if p.last_sync else "never"
        lines.append(f"  {p.id}  {p.name:<24}  [{p.trust_level}]  {p.transport}://{p.address[:40]}")
        lines.append(f"         min_shi: {p.min_shi}  |  last sync: {last}  |  syncs: {p.sync_count}  |  {status}")
        if p.tags_filter:
            lines.append(f"         tags: {', '.join(p.tags_filter)}")
        lines.append("")
    return "\n".join(lines)
