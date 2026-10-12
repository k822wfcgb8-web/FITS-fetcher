"""Archive modules (S-20). Each one is independent; add new archives to ARCHIVES."""
from fits_fetcher.archives.base import Archive, ArchiveError, Product, Target
from fits_fetcher.archives.eso import EsoArchive
from fits_fetcher.archives.irsa import IrsaArchive
from fits_fetcher.archives.mast import MastArchive

ARCHIVES: dict[str, type[Archive]] = {"MAST": MastArchive, "ESO": EsoArchive, "IRSA": IrsaArchive}
# Planned (verified in verify/FINDINGS.md, not built yet). Shown in the UI as unavailable.
PLANNED = ["CADC"]

__all__ = ["ARCHIVES", "PLANNED", "Archive", "ArchiveError", "Product", "Target"]
