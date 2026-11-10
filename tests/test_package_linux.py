import hashlib
import runpy
from pathlib import Path
from zipfile import ZipFile

import pytest

PACKAGE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package-linux.py"
package_appimage = runpy.run_path(str(PACKAGE_SCRIPT))["package_appimage"]


@pytest.mark.parametrize("architecture", ["x86_64", "aarch64"])
@pytest.mark.parametrize("version", ["0.1.3", "0.2.0"])
def test_release_zip_keeps_version_out_of_bundled_filenames(
    tmp_path, architecture, version
):
    appimage = tmp_path / f"Ounce-bt-{architecture}.AppImage"
    contents = b"AppImage test contents"
    appimage.write_bytes(contents)

    output = package_appimage(appimage, version)

    assert output == tmp_path / f"Ounce-bt-{version}-linux-{architecture}.zip"
    assert not output.with_suffix(".zip.tmp").exists()
    bundle_name = f"Ounce-bt-linux-{architecture}"
    checksum_name = f"{appimage.name}.sha256"
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            f"{bundle_name}/{appimage.name}",
            f"{bundle_name}/run-with-hci-caps.sh",
            f"{bundle_name}/{checksum_name}",
            f"{bundle_name}/README.txt",
        }
        assert archive.read(f"{bundle_name}/{appimage.name}") == contents
        assert archive.read(f"{bundle_name}/{checksum_name}").decode() == (
            f"{hashlib.sha256(contents).hexdigest()}  {appimage.name}\n"
        )
        instructions = archive.read(f"{bundle_name}/README.txt").decode()
        assert f'./run-with-hci-caps.sh "$PWD/{appimage.name}" usb:0' in instructions
        assert f"sha256sum -c {checksum_name}" in instructions
        assert version not in instructions
        for filename in (appimage.name, "run-with-hci-caps.sh", checksum_name, "README.txt"):
            entry = archive.getinfo(f"{bundle_name}/{filename}")
            assert entry.create_system == 3
            expected_mode = (
                0o100755 if filename in (appimage.name, "run-with-hci-caps.sh")
                else 0o100644
            )
            assert entry.external_attr >> 16 == expected_mode


@pytest.mark.parametrize("filename", ["missing.AppImage", "not-an-appimage.txt"])
def test_package_rejects_invalid_appimage(tmp_path, filename):
    appimage = tmp_path / filename
    if appimage.suffix != ".AppImage":
        appimage.write_bytes(b"not an AppImage")

    with pytest.raises(ValueError, match="Expected an existing .AppImage file"):
        package_appimage(appimage, "0.1.3")
