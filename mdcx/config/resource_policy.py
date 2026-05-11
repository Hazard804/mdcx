from dataclasses import dataclass

from .enums import DownloadableFile, KeepableFile


@dataclass(frozen=True)
class ResourcePolicy:
    downloadable: DownloadableFile
    keepable: KeepableFile
    download_files: list[DownloadableFile]
    keep_files: list[KeepableFile]

    @property
    def should_download(self) -> bool:
        return self.downloadable in self.download_files

    @property
    def should_keep(self) -> bool:
        return self.keepable in self.keep_files

    @property
    def should_remove_existing(self) -> bool:
        return not self.should_download and not self.should_keep


def resource_policy(
    downloadable: DownloadableFile,
    keepable: KeepableFile,
    *,
    download_files: list[DownloadableFile],
    keep_files: list[KeepableFile],
) -> ResourcePolicy:
    return ResourcePolicy(downloadable, keepable, download_files, keep_files)
