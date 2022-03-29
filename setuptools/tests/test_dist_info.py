"""Test .dist-info style distributions.
"""
import pathlib
import subprocess
import sys
from functools import partial
from unittest.mock import patch

import pytest

import pkg_resources
from setuptools.archive_util import unpack_archive
from .textwrap import DALS


read = partial(pathlib.Path.read_text, encoding="utf-8")


class TestDistInfo:

    metadata_base = DALS("""
        Metadata-Version: 1.2
        Requires-Dist: splort (==4)
        Provides-Extra: baz
        Requires-Dist: quux (>=1.1); extra == 'baz'
        """)

    @classmethod
    def build_metadata(cls, **kwargs):
        lines = (
            '{key}: {value}\n'.format(**locals())
            for key, value in kwargs.items()
        )
        return cls.metadata_base + ''.join(lines)

    @pytest.fixture
    def metadata(self, tmpdir):
        dist_info_name = 'VersionedDistribution-2.718.dist-info'
        versioned = tmpdir / dist_info_name
        versioned.mkdir()
        filename = versioned / 'METADATA'
        content = self.build_metadata(
            Name='VersionedDistribution',
        )
        filename.write_text(content, encoding='utf-8')

        dist_info_name = 'UnversionedDistribution.dist-info'
        unversioned = tmpdir / dist_info_name
        unversioned.mkdir()
        filename = unversioned / 'METADATA'
        content = self.build_metadata(
            Name='UnversionedDistribution',
            Version='0.3',
        )
        filename.write_text(content, encoding='utf-8')

        return str(tmpdir)

    def test_distinfo(self, metadata):
        dists = dict(
            (d.project_name, d)
            for d in pkg_resources.find_distributions(metadata)
        )

        assert len(dists) == 2, dists

        unversioned = dists['UnversionedDistribution']
        versioned = dists['VersionedDistribution']

        assert versioned.version == '2.718'  # from filename
        assert unversioned.version == '0.3'  # from METADATA

    def test_conditional_dependencies(self, metadata):
        specs = 'splort==4', 'quux>=1.1'
        requires = list(map(pkg_resources.Requirement.parse, specs))

        for d in pkg_resources.find_distributions(metadata):
            assert d.requires() == requires[:1]
            assert d.requires(extras=('baz',)) == [
                requires[0],
                pkg_resources.Requirement.parse('quux>=1.1;extra=="baz"'),
            ]
            assert d.extras == ['baz']


class TestWheelCompatibility:
    SETUPCFG = DALS("""
    [metadata]
    name = proj
    version = 42

    [options]
    install_requires = foo>=12; sys_platform != "linux"

    [options.extras_require]
    test = pytest

    [options.entry_points]
    console_scripts =
        executable-name = my_package.module:function
    discover =
        myproj = my_package.other_module:function
    """)

    FROZEN_TIME = "20220329"
    EGG_INFO_OPTS = [
        # Related: #3077 #2872
        ("", ""),
        (".post", "[egg_info]\ntag_build = post\n"),
        (".post", "[egg_info]\ntag_build = .post\n"),
        (f".post{FROZEN_TIME}", "[egg_info]\ntag_build = post\ntag_date = 1\n"),
        (".dev", "[egg_info]\ntag_build = .dev\n"),
        (f".dev{FROZEN_TIME}", "[egg_info]\ntag_build = .dev\ntag_date = 1\n"),
        ("a1", "[egg_info]\ntag_build = .a1\n"),
        ("+local", "[egg_info]\ntag_build = +local\n"),
    ]

    @pytest.mark.parametrize("suffix,cfg", EGG_INFO_OPTS)
    @patch("setuptools.command.egg_info.time.strftime", FROZEN_TIME)
    def test_dist_info_is_the_same_as_in_wheel(self, tmp_path, suffix, cfg):
        config = self.SETUPCFG + cfg

        for i in "dir_wheel", "dir_dist":
            (tmp_path / i).mkdir()
            (tmp_path / i / "setup.cfg").write_text(config, encoding="utf-8")

        run_command("bdist_wheel", cwd=tmp_path / "dir_wheel")
        wheel = next(tmp_path.glob("dir_wheel/dist/*.whl"))
        unpack_archive(wheel, tmp_path / "unpack")
        wheel_dist_info = next(tmp_path.glob("unpack/*.dist-info"))

        run_command("dist_info", cwd=tmp_path / "dir_dist")
        dist_info = next(tmp_path.glob("dir_dist/*.dist-info"))

        assert dist_info.name == wheel_dist_info.name
        assert dist_info.name.startswith(f"proj-42{suffix}")
        for file in "METADATA", "entry_points.txt":
            assert read(dist_info / file) == read(wheel_dist_info / file)


def run_command(*cmd, **kwargs):
    opts = {"stderr": subprocess.STDOUT, "text": True, **kwargs}
    cmd = [sys.executable, "-c", "__import__('setuptools').setup()", *cmd]
    return subprocess.check_output(cmd, **opts)
