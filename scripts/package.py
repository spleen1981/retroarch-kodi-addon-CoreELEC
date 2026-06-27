"""Packaging: assemble the addon dir, generate manifests, zip it up."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from . import langdata

log = logging.getLogger(__name__)


# Subprocess output target -- mirrors lakka.configure_subprocess.
_SUBPROC_KW: dict = {}


def configure_subprocess(*, stdout=None, stderr=None) -> None:
    """Set default stdout/stderr for every subprocess.run in this module."""
    global _SUBPROC_KW
    _SUBPROC_KW = {}
    if stdout is not None:
        _SUBPROC_KW["stdout"] = stdout
    if stderr is not None:
        _SUBPROC_KW["stderr"] = stderr


def _run(args, **kw):
    """subprocess.run wrapper honoring `configure_subprocess` defaults."""
    merged = {**_SUBPROC_KW, **kw}
    return subprocess.run(args, **merged)


# `.in` files that the *late* render stage owns. The eager render stage
# leaves these alone so they can be rendered by emit_addon_xml after the
# build knows the addon version, provider, etc.
_LATE_RENDERED_IN_FILES: frozenset[str] = frozenset({"addon.xml.in"})


# =========================================================== move_artifacts


# Map (Lakka build sub-path) -> (addon-dir sub-path).
# v2: the DLC packages (shaders / database / assets / overlays) are always
# bundled, so a single _MOVES table covers everything.
_MOVES: tuple[tuple[str, str], ...] = (
    ("etc/retroarch.cfg",              "config/retroarch.cfg"),
    ("usr/bin",                        "bin"),
    ("usr/lib",                        "lib"),
    ("usr/share/audio_filters",        "resources/audio_filters"),
    ("usr/share/video_filters",        "resources/video_filters"),
    ("usr/share/retroarch/system",     "resources/system"),
    ("etc/retroarch-joypad-autoconfig","resources/joypads"),
    ("usr/share/common-shaders",       "resources/shaders"),
    ("usr/share/libretro-database",    "resources/database"),
    ("usr/share/retroarch-assets",     "resources/assets"),
    ("usr/share/retroarch-overlays",   "resources/overlays"),
)


def move_artifacts(staging: Path, addon_dir: Path) -> None:
    """Move Lakka build output from `staging` into the addon layout."""
    for src_rel, dst_rel in _MOVES:
        src = staging / src_rel
        dst = addon_dir / dst_rel
        if not src.exists():
            log.warning("package: missing artifact %s", src)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        shutil.move(str(src), str(dst))
        log.info("package: moved %s -> %s", src_rel, dst_rel)


# ================================================================ clean_lib ==


# Subdirectories of lib/ that are allowed to survive cleaning.
_LIB_ALLOWED_SUBDIRS: frozenset[str] = frozenset({"libretro"})


# libs whose SONAME stem matches these prefixes must go to lib-gpu/
# instead of lib/. They are loaded conditionally by AppRun only on
# framebuffer-only platforms (no /dev/dri/card0).
_GPU_LIB_PREFIXES: tuple[str, ...] = ("libgbm",)

# Libs that must never be bundled — they are either kernel-tied (GPU
# userspace driver) or always present on the host (glibc family).
_HOST_ONLY_LIBS: frozenset[str] = frozenset({
    # glibc / dynamic linker — always present on the target system
    "libc", "libm", "libpthread", "libdl", "librt", "libgcc_s",
    "libstdc++",
    "ld-linux", "ld-linux-aarch64", "ld-linux-armhf", "ld-linux-x86-64",
    # libcec on Amlogic is kernel-tied (AOCEC hardware adapter) — the
    # Lakka-built libcec.so.7 lacks Amlogic support. AppRun creates a
    # runtime compat symlink @LIBCEC_SONAME@ -> system libcec in /tmp.
    "libcec",
    # Mali/GPU userspace — kernel-tied, must come from the host system
    "libmali", "libEGL", "libGL",
    "libGLESv2", "libGLESv1_CM",
    "libGLdispatch", "libOpenGL",
    "libGLX",
    # libdrm — kept on system for DRM platforms; FB-only gets it via lib-gpu
    "libdrm",
})


def clean_lib(addon_dir: Path) -> None:
    """Remove build artefacts from lib/ that must not ship.

    After move_artifacts copies usr/lib verbatim, lib/ contains static
    archives (.a), libtool files (.la), pkg-config data, cmake files, and
    various subdirectories from devel packages. Only shared libraries
    (.so / .so.N.N.N symlink chains) and the libretro/ subdir are kept.
    """
    lib_dir = addon_dir / "lib"
    if not lib_dir.is_dir():
        return

    for entry in list(lib_dir.iterdir()):
        if entry.is_dir() and not entry.is_symlink():
            if entry.name not in _LIB_ALLOWED_SUBDIRS:
                shutil.rmtree(entry)
                log.debug("clean_lib: removed dir %s", entry.name)
        elif entry.is_file() or entry.is_symlink():
            name = entry.name
            # Keep anything that looks like a shared library:
            # foo.so  /  foo.so.2  /  foo.so.2.0.1
            if re.search(r"\.so(\.\d+)*$", name):
                continue
            entry.unlink(missing_ok=True)
            log.debug("clean_lib: removed file %s", name)

    log.info("package: lib/ cleaned")


# ============================================================ collect_gpu_libs


def collect_gpu_libs(addon_dir: Path) -> None:
    """Move GPU-fallback libs from lib/ to lib-gpu/.

    lib-gpu/ is added to LD_LIBRARY_PATH by AppRun only on framebuffer-only
    platforms (no /dev/dri/card0). This lets DRM platforms use their system
    libgbm (which matches the running Mali kernel driver) while still
    satisfying the link-time dependency on FB-only systems where the lib is
    absent.
    """
    lib_dir = addon_dir / "lib"
    lib_gpu_dir = addon_dir / "lib-gpu"

    candidates = [
        e for e in lib_dir.iterdir()
        if (e.is_file() or e.is_symlink())
        and any(e.name.startswith(pfx) for pfx in _GPU_LIB_PREFIXES)
    ]
    if not candidates:
        log.info("package: no GPU-fallback libs found in lib/")
        return

    lib_gpu_dir.mkdir(exist_ok=True)
    for entry in candidates:
        dst = lib_gpu_dir / entry.name
        shutil.move(str(entry), str(dst))
        log.info("package: %s -> lib-gpu/", entry.name)


# ============================================================== collect_deps ==


def collect_deps(addon_dir: Path, lakka_build_dir: Path,
                 readelf: str = "readelf") -> None:
    """Walk ELF dependencies of all binaries and copy missing .so into lib/.

    Uses `readelf -d` (cross-aware: pass the full toolchain readelf path via
    `readelf`) to read DT_NEEDED entries. Walks transitively. Skips libs
    already present in lib/ or lib-gpu/, host-only libs, and GPU libs
    (those belong to the system on DRM platforms).

    `lakka_build_dir` is the per-device Lakka build root, e.g.
    `Lakka-LibreELEC/build.Lakka-AMLGX.aarch64`. Libraries are resolved from
    two locations under it:

        toolchain/lib/
            Sysroot libs shipped with the cross-compiler (libc, libstdc++,
            and other base target libs).

        install_pkg/PKGNAME-VERSION/usr/lib/   (glob)
            Per-package install trees produced by the Lakka build.
    """
    lib_dir = addon_dir / "lib"
    lib_gpu_dir = addon_dir / "lib-gpu"

    # Build a quick lookup of what is already bundled.
    def _bundled() -> set[str]:
        bundled: set[str] = set()
        for d in (lib_dir, lib_gpu_dir):
            if d.is_dir():
                bundled.update(e.name for e in d.iterdir()
                               if e.is_file() or e.is_symlink())
        return bundled

    # 1) toolchain/lib/ — base target sysroot libs.
    # 2) install_pkg/*/usr/lib/ — every built package's lib dir.
    #    Also check install/lib/ and install/usr/lib/<arch-triplet>/ as
    #    some packages install there.
    search_dirs: list[Path] = []
    toolchain_lib = lakka_build_dir / "toolchain" / "lib"
    if toolchain_lib.is_dir():
        search_dirs.append(toolchain_lib)

    install_pkg = lakka_build_dir / "install_pkg"
    if install_pkg.is_dir():
        for pkg_dir in sorted(install_pkg.iterdir()):
            for sub in (
                "usr/lib",
                "lib",
                "usr/lib/aarch64-linux-gnu",
                "usr/lib/arm-linux-gnueabihf",
            ):
                d = pkg_dir / sub
                if d.is_dir():
                    search_dirs.append(d)
                    # Also search immediate subdirectories — some packages
                    # install private libs one level deeper (e.g. PulseAudio
                    # puts libpulsecommon in usr/lib/pulseaudio/).
                    for child in d.iterdir():
                        if child.is_dir():
                            search_dirs.append(child)

    def _find_so(soname: str) -> Path | None:
        for d in search_dirs:
            candidate = d / soname
            if candidate.exists():
                return candidate
        return None

    def _stem(soname: str) -> str:
        """Return the base library name without .so* suffix."""
        return soname.split(".so")[0]

    def _is_elf(path: Path) -> bool:
        """Check ELF magic bytes — skips shell scripts and other non-ELF files."""
        try:
            with path.open("rb") as fh:
                return fh.read(4) == b"\x7fELF"
        except OSError:
            return False

    def _readelf_needed(binary: Path) -> list[str]:
        if not _is_elf(binary):
            return []
        try:
            out = subprocess.check_output(
                [readelf, "-d", str(binary)],
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            log.warning("collect_deps: readelf failed on %s: %s", binary.name, exc)
            return []
        return re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", out)

    # Seed the queue with all ELF files under bin/ and lib/ (including cores).
    queue: list[Path] = []
    for search_root in (addon_dir / "bin", lib_dir,
                        lib_dir / "libretro", lib_gpu_dir):
        if search_root.is_dir():
            queue.extend(
                e for e in search_root.rglob("*")
                if (e.is_file() and not e.is_symlink()
                    and re.search(r"(\.so(\.\d+)*$|^[^.]+$)", e.name))
            )

    visited: set[str] = set()
    while queue:
        binary = queue.pop()
        for soname in _readelf_needed(binary):
            if soname in visited:
                continue
            visited.add(soname)

            stem = _stem(soname)
            if stem in _HOST_ONLY_LIBS:
                continue
            if soname in _bundled():
                continue

            src = _find_so(soname)
            if src is None:
                log.warning("collect_deps: %s not found in Lakka build", soname)
                continue

            # GPU-fallback libs go to lib-gpu/, everything else to lib/.
            dst_dir = (lib_gpu_dir if any(soname.startswith(pfx)
                                          for pfx in _GPU_LIB_PREFIXES)
                       else lib_dir)
            dst_dir.mkdir(exist_ok=True)
            shutil.copy2(src, dst_dir / soname)
            log.info("collect_deps: added %s -> %s/", soname, dst_dir.name)
            queue.append(dst_dir / soname)  # walk transitivo



# ======================================================= collect_pkg_deps ==


def collect_pkg_deps(addon_dir: Path, lakka_dir: Path,
                     lakka_build_dir: Path,
                     package_list: dict[str, tuple[str, ...]],
                     subdirs: dict[str, str],
                     readelf: str = "readelf") -> None:
    """Bundle .so files from PKG_DEPENDS_TARGET of compiled packages.

    readelf -d only sees DT_NEEDED (static link-time deps). Libraries loaded
    via dlopen() at runtime are invisible to it. This function closes that gap:
    for every package we compile, we parse its PKG_DEPENDS_TARGET from the
    Lakka package.mk and bundle all .so files found in those dep packages'
    install_pkg dirs.

    Example: cec-mini-kb has PKG_DEPENDS_TARGET="toolchain libcec" →
    we find libcec-7.1.1/ in install_pkg/ and copy libcec.so.7 into lib/.
    """
    lib_dir = addon_dir / "lib"
    lib_dir.mkdir(exist_ok=True)

    install_pkg = lakka_build_dir / "install_pkg"
    if not install_pkg.is_dir():
        return

    # Build a map: package-name-prefix → list of install_pkg subdirs
    pkg_install_map: dict[str, list[Path]] = {}
    for d in install_pkg.iterdir():
        # dir names are "pkgname-version" or "pkgname-HASH"
        prefix = d.name.split("-")[0]
        pkg_install_map.setdefault(prefix, []).append(d)

    def _already_bundled(name: str) -> bool:
        return (lib_dir / name).exists()

    def _find_so_in_pkg(pkg_name: str) -> list[Path]:
        """Return all .so* files from a dep package's install dirs."""
        found: list[Path] = []
        for pkg_dir in pkg_install_map.get(pkg_name, []):
            for sub in ("usr/lib", "lib",
                        "usr/lib/aarch64-linux-gnu",
                        "usr/lib/arm-linux-gnueabihf"):
                d = pkg_dir / sub
                if d.is_dir():
                    found.extend(
                        f for f in d.iterdir()
                        if (f.is_file() or f.is_symlink())
                        and re.search(r"\.so(\.\d+)*$", f.name)
                    )
                    for child in d.iterdir():
                        if child.is_dir():
                            found.extend(
                                f for f in child.iterdir()
                                if (f.is_file() or f.is_symlink())
                                and re.search(r"\.so(\.\d+)*$", f.name)
                            )
        return found

    # Packages whose PKG_DEPENDS_TARGET we should walk.
    # Focus on tool packages (executables that may dlopen libs at runtime).
    skip_deps = frozenset({
        "toolchain", "toolchain_pkg_dir",
        "virtual", "glibc", "linux", "linux-headers",
    })

    for family, pkgs in package_list.items():
        subdir = subdirs.get(family)
        if subdir is None:
            continue
        for pkg in pkgs:
            pkg_mk = lakka_dir / "packages" / subdir / pkg / "package.mk"
            if not pkg_mk.is_file():
                continue
            deps = _parse_pkg_depends_target(pkg_mk)
            for dep in deps:
                if dep in skip_deps:
                    continue
                sos = _find_so_in_pkg(dep)
                for so in sos:
                    stem = _stem_from_path(so)
                    if stem in _HOST_ONLY_LIBS:
                        continue
                    if _already_bundled(so.name):
                        continue
                    try:
                        shutil.copy2(so, lib_dir / so.name)
                        log.info("collect_pkg_deps: %s (dep of %s) -> lib/",
                                 so.name, pkg)
                    except OSError as exc:
                        log.warning("collect_pkg_deps: cannot copy %s: %s",
                                    so.name, exc)


def _parse_pkg_depends_target(pkg_mk: Path) -> list[str]:
    """Extract the space-separated package list from PKG_DEPENDS_TARGET."""
    text = pkg_mk.read_text(encoding="utf-8", errors="replace")
    parts: list[str] = []
    in_var = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_var:
            if not stripped.startswith("PKG_DEPENDS_TARGET"):
                continue
            _, _, rhs = stripped.partition("=")
            in_var = True
        else:
            rhs = stripped
        rhs = rhs.strip().strip('"').strip("'")
        continuation = rhs.endswith("\\")
        if continuation:
            rhs = rhs[:-1]
        parts.extend(rhs.split())
        if not continuation:
            break
    return parts


def _stem_from_path(p: Path) -> str:
    return p.name.split(".so")[0]


# ============================================================= stage_appimage


def _detect_soname(lakka_build_dir: Path, pkg_prefix: str,
                   lib_name: str, default: str) -> str:
    """Return the SONAME for lib_name from the Lakka build output.

    Strategy (in order):
    1. Follow the unversioned dev symlink: lib_name.so → lib_name.so.N
       e.g. libcec.so → libcec.so.7  (most packages have this)
    2. Find a lib_name.so.N file directly (single-number SONAME pattern)
       e.g. libudev.so.1  (systemd may omit the unversioned dev symlink)

    Falls back to `default` if neither strategy finds a match.
    """
    soname_re = re.compile(rf"^{re.escape(lib_name)}\.so\.\d+$")
    install_pkg = lakka_build_dir / "install_pkg"
    if install_pkg.is_dir():
        for pkg_dir in sorted(install_pkg.iterdir()):
            if not pkg_dir.name.startswith(pkg_prefix):
                continue
            lib_dir = pkg_dir / "usr" / "lib"
            if not lib_dir.is_dir():
                continue
            # Strategy 1: unversioned dev symlink
            unversioned = lib_dir / f"{lib_name}.so"
            if unversioned.is_symlink():
                target = Path(os.readlink(str(unversioned))).name
                if soname_re.match(target):
                    log.info("stage_appimage: %s SONAME=%s (symlink in %s)",
                             lib_name, target, pkg_dir.name)
                    return target
            # Strategy 2: SONAME file present directly
            for entry in lib_dir.iterdir():
                if soname_re.match(entry.name):
                    log.info("stage_appimage: %s SONAME=%s (file in %s)",
                             lib_name, entry.name, pkg_dir.name)
                    return entry.name
    log.warning("stage_appimage: %s SONAME not detected, using default %s",
                lib_name, default)
    return default


def stage_appimage(addon_dir: Path, appimage_dir: Path,
                   output_dir: Path, addon_name: str,
                   lakka_build_dir: Path | None = None,
                   appimage_version: str = "") -> None:
    """Move retroarch + libs from addon_dir into the AppImage staging dir.

    After this step:
      appimage_dir/bin/retroarch    the main binary
      appimage_dir/lib/             all shared libs
      appimage_dir/lib-gpu/         GPU-fallback libs (libgbm)
      appimage_dir/AppRun           rendered entry point (from output/AppRun.in)

    addon_dir/bin/ retains only the standalone tools (cec-mini-kb, etc.).
    addon_dir/lib/ and addon_dir/lib-gpu/ are removed (moved to AppImage).
    """
    appimage_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("bin", "lib", "lib-gpu"):
        (appimage_dir / sub).mkdir(exist_ok=True)

    # Move entire bin/ into AppImage — all compiled binaries (retroarch,
    # cec-mini-kb, xbox360-controllers-shutdown, …) are bundled together.
    # The thin addon has no loose binaries; tools are invoked via the
    # AppImage --run sub-command.
    bin_src = addon_dir / "bin"
    bin_dst = appimage_dir / "bin"
    if bin_src.is_dir():
        if bin_dst.exists():
            shutil.rmtree(bin_dst)
        shutil.move(str(bin_src), str(bin_dst))
        log.info("stage_appimage: moved bin/ -> appimage/bin/")
    else:
        log.warning("stage_appimage: bin/ not found in addon_dir")

    # Move entire lib/ and lib-gpu/ into AppImage.
    for subdir in ("lib", "lib-gpu"):
        src = addon_dir / subdir
        dst = appimage_dir / subdir
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(src), str(dst))
            log.info("stage_appimage: moved %s -> appimage/%s/", subdir, subdir)

    # Move RetroArch resources into the AppImage. They are read-only by
    # nature and update with the AppImage stream; ra_sync merges them into
    # the user RA config dir on each launch. The addon ZIP keeps only the
    # Kodi-side resources (icon, fanart, language, settings.xml).
    _RA_RESOURCES = (
        "audio_filters", "video_filters", "system", "joypads",
        "shaders", "database", "overlays", "assets",
    )
    appimage_resources = appimage_dir / "resources"
    appimage_resources.mkdir(exist_ok=True)
    for sub in _RA_RESOURCES:
        src = addon_dir / "resources" / sub
        if not src.is_dir():
            continue
        dst_res = appimage_resources / sub
        if dst_res.exists():
            shutil.rmtree(dst_res)
        shutil.move(str(src), str(dst_res))
        log.info("stage_appimage: moved resources/%s -> appimage/resources/%s",
                 sub, sub)

    # Ship the standalone ra_sync Python package inside the AppImage.
    # AppRun invokes it on every launch to merge the resources above into
    # the user RA config dir. Stdlib only, no ra.* imports.
    appimage_lib = appimage_dir / "lib"
    appimage_lib.mkdir(exist_ok=True)
    src_sync = output_dir / "ra_sync"
    dst_sync = appimage_lib / "ra_sync"
    if src_sync.is_dir():
        if dst_sync.exists():
            shutil.rmtree(dst_sync)
        shutil.copytree(src_sync, dst_sync)
        log.info("stage_appimage: shipped ra_sync module into AppImage")
    else:
        log.warning("stage_appimage: %s missing, AppRun sync will no-op",
                    src_sync)

    # Restore flattened .symlink placeholders in appimage lib/ at build time.
    # (At runtime the squashfs is read-only so this must happen here.)
    _restore_flattened_symlinks(appimage_dir / "lib")

    # Detect kernel-tied lib SONAMEs from the Lakka build by following the
    # unversioned .so symlinks in install_pkg. Baked into AppRun so the
    # compat dir uses the exact SONAME the binaries were compiled against.
    _lbd = lakka_build_dir or Path("/nonexistent")
    libcec_soname  = _detect_soname(_lbd, "libcec",  "libcec",  "libcec.so.7")
    libudev_soname = _detect_soname(_lbd, "systemd", "libudev", "libudev.so.1")

    # Render AppRun from output/AppRun.in.
    apprun_template = output_dir / "AppRun.in"
    if apprun_template.exists():
        rendered = (
            apprun_template.read_text(encoding="utf-8")
            .replace("@ADDON_NAME@", addon_name)
            .replace("@LIBCEC_SONAME@",  libcec_soname)
            .replace("@LIBUDEV_SONAME@", libudev_soname)
            .replace("@APPIMAGE_VERSION@", appimage_version or "0.0.0")
        )
        apprun_dst = appimage_dir / "AppRun"
        apprun_dst.write_text(rendered, encoding="utf-8")
        os.chmod(apprun_dst, 0o755)
        log.info("stage_appimage: wrote AppRun")


def _strip_hidden(root: Path) -> None:
    """Remove hidden files and directories (name starts with '.') recursively.

    Prevents accidental inclusion of .git, __pycache__, .DS_Store and similar
    artefacts in the AppImage squashfs or the addon ZIP.
    """
    for entry in sorted(root.rglob(".*")):
        if not entry.exists():
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
            log.debug("package: removed hidden dir %s", entry.relative_to(root))
        else:
            entry.unlink(missing_ok=True)
            log.debug("package: removed hidden file %s", entry.relative_to(root))


def create_appimage(appimage_dir: Path, output_path: Path,
                    runtime: str) -> Path:
    """Pack appimage_dir into an AppImage at output_path.

    Assembles the AppImage manually:
      1. mksquashfs compresses the AppDir with zstd — the only compression
         the AppImageKit fuse2 runtime (squashfuse 0.1.100) supports.
      2. The AppImage is cat(runtime, squashfs): the type-2 format is a
         plain concatenation of the runtime ELF and the squashfs image.

    Requires `mksquashfs` (squashfs-tools) on the host PATH.

    Returns output_path.
    """
    _strip_hidden(appimage_dir)
    squashfs = output_path.with_suffix(".squashfs")
    try:
        subprocess.check_call(
            ["mksquashfs", str(appimage_dir), str(squashfs),
             "-comp", "zstd", "-noappend", "-no-progress", "-b", "1048576"],
            **_SUBPROC_KW,
        )
        with open(output_path, "wb") as out:
            for src in (runtime, str(squashfs)):
                with open(src, "rb") as f:
                    shutil.copyfileobj(f, out)
        os.chmod(output_path, 0o755)
    finally:
        squashfs.unlink(missing_ok=True)
    log.info("package: AppImage -> %s", output_path.name)
    return output_path


def _restore_flattened_symlinks(root: Path) -> None:
    """Restore *.symlink placeholder files to real symlinks.

    Called at build time on the AppImage lib/ staging dir so the squashfs
    (which is read-only at runtime) contains proper symlinks from the start.
    """
    if not root.is_dir():
        return
    for placeholder in root.rglob("*.symlink"):
        try:
            target = placeholder.read_text(encoding="utf-8").strip()
        except OSError as exc:
            log.warning("stage_appimage: cannot read %s: %s", placeholder, exc)
            continue
        if not target:
            continue
        link_path = placeholder.with_suffix("")
        try:
            link_path.unlink(missing_ok=True)
            link_path.symlink_to(target)
            placeholder.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("stage_appimage: cannot create symlink %s -> %s: %s",
                        link_path, target, exc)


# ===================================================== add_fallback_cores ==


def add_fallback_cores(repo_root: Path, addon_dir: Path, profile) -> None:
    """Unzip pre-compiled cores from `fallback-precompiled-cores/<arch>/*.zip`."""
    if not profile.fallback_subdir or not profile.cores_fallback:
        return
    src_dir = repo_root / "fallback-precompiled-cores" / profile.fallback_subdir
    dst = addon_dir / "lib" / "libretro"
    dst.mkdir(parents=True, exist_ok=True)
    for core in profile.cores_fallback:
        zip_path = src_dir / f"{core}_libretro.so.zip"
        if not zip_path.is_file():
            log.warning("package: missing fallback zip %s", zip_path)
            continue
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dst)
        _maybe_clone_core_info(dst, core)
        log.info("package: unpacked fallback %s", core)


def _maybe_clone_core_info(libretro_dir: Path, core: str) -> None:
    """For flycast_xtreme, create the .info file by tweaking flycast's."""
    if core != "flycast_xtreme":
        return
    src = libretro_dir / "flycast_libretro.info"
    dst = libretro_dir / "flycast_xtreme_libretro.info"
    if not src.is_file():
        return
    text = src.read_text(encoding="utf-8")
    dst.write_text(text.replace("Flycast", "Flycast xtreme"), encoding="utf-8")


# ===================================================== install_committed_src


def install_committed_source(output_dir: Path, addon_dir: Path,
                             addon_name: str) -> None:
    """Copy `output/` into the addon dir, then render `.in` files.

    `output/` is the part of the tree that lives in version control: the
    Python package, the autostart shim, settings.xml schema, the addon.xml
    template, settings-default.xml, and resources/icon.png / fanart.jpg.

    Any file whose name ends in `.in` is treated as a template:
        * `addon.xml.in` is left as-is — `emit_addon_xml` renders it later
          once metadata (version, provider, lang block, changelog) is known.
        * Every other `.in` file is rendered with `@ADDON_NAME@` substitution
          and the rendered output replaces the template in the addon tree.
    """
    # ra_sync ships INSIDE the AppImage only (stage_appimage copies it
    # to $APPDIR/lib/ra_sync). Do not include it in the addon ZIP.
    _ADDON_EXCLUDE = {"ra_sync"}
    for entry in output_dir.iterdir():
        if entry.name in _ADDON_EXCLUDE:
            continue
        dst = addon_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, dst)

    _render_in_files(addon_dir, addon_name)
    _chmod_executables(addon_dir)
    # AppRun belongs inside the AppImage only — remove it from the thin addon
    # if install_committed_source copied it from output/AppRun.in.
    (addon_dir / "AppRun").unlink(missing_ok=True)
    (addon_dir / "AppRun.in").unlink(missing_ok=True)


def _render_in_files(addon_dir: Path, addon_name: str) -> None:
    """Render every eager `.in` file under `addon_dir` (recursive).

    Templates owned by the late stage (see `_LATE_RENDERED_IN_FILES`) are
    skipped here. For every other template:

        foo/bar.ext.in  ->  foo/bar.ext   (with `@ADDON_NAME@` substituted)

    The `.in` source is removed after rendering so it doesn't end up in
    the shipped zip.
    """
    for src in addon_dir.rglob("*.in"):
        if not src.is_file():
            continue
        if src.name in _LATE_RENDERED_IN_FILES:
            continue
        rendered = src.read_text(encoding="utf-8").replace(
            "@ADDON_NAME@", addon_name
        )
        dst = src.with_suffix("")  # strip the trailing `.in`
        dst.write_text(rendered, encoding="utf-8")
        src.unlink()


def _chmod_executables(addon_dir: Path) -> None:
    """`+x` shell scripts and executables in the thin addon root."""
    # bin/ has been moved entirely into the AppImage by stage_appimage;
    # only the shell scripts at the addon root need +x here.
    for name in ("ra_autostart.sh",):
        p = addon_dir / name
        if p.is_file():
            os.chmod(p, 0o755)
    # AppRun is handled by stage_appimage, but guard here too in case the
    # order ever changes.
    apprun = addon_dir / "AppRun"
    if apprun.is_file():
        os.chmod(apprun, 0o755)


# ========================================================= emit_addon_xml ==


def emit_addon_xml(addon_dir: Path, addon_name: str, addon_version: str,
                   provider: str, ra_name_suffix: str, *,
                   changelog: Path) -> None:
    """Fill in addon.xml.in placeholders and write addon.xml into the addon dir.

    Pairs with `install_committed_source`, which leaves `addon.xml.in` in
    place precisely so this late stage can render it once the build knows
    the metadata that wasn't available earlier.
    """
    template_path = addon_dir / "addon.xml.in"
    text = template_path.read_text(encoding="utf-8")

    lang_meta = _render_lang_metadata(ra_name_suffix)
    changelog_text = _read_changelog(changelog)

    text = (text
            .replace("@ADDON_NAME@", addon_name)
            .replace("@ADDON_VERSION@", addon_version)
            .replace("@PROVIDER@", provider)
            .replace("@LANG_METADATA@", lang_meta)
            .replace("@CHANGELOG@", changelog_text))

    (addon_dir / "addon.xml").write_text(text, encoding="utf-8")
    # The .in template doesn't need to ship.
    template_path.unlink(missing_ok=True)


def _render_lang_metadata(ra_name_suffix: str) -> str:
    """Render <summary>/<description>/<disclaimer> for every language."""
    lines: list[str] = []
    for lang_code in langdata.LANGUAGES:
        kodi_tag = _kodi_lang_tag(lang_code)
        summary = langdata.translate(0, lang_code, ra_name_suffix=ra_name_suffix)
        description = langdata.translate(1, lang_code, ra_name_suffix=ra_name_suffix)
        disclaimer = langdata.translate(2, lang_code, ra_name_suffix=ra_name_suffix)
        lines.append(f'        <summary lang="{kodi_tag}">{_xml_escape(summary)}</summary>')
        lines.append(f'        <description lang="{kodi_tag}">{_xml_escape(description)}</description>')
        lines.append(f'        <disclaimer lang="{kodi_tag}">{_xml_escape(disclaimer)}</disclaimer>')
    return "\n".join(lines)


def _kodi_lang_tag(lang_code: str) -> str:
    # `en_gb` -> `en_GB`. Kodi addon.xml expects an uppercase region.
    parts = lang_code.split("_", 1)
    if len(parts) != 2:
        return lang_code
    return f"{parts[0]}_{parts[1].upper()}"


def _xml_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def _read_changelog(path: Path) -> str:
    if not path.is_file():
        return ""
    return _xml_escape(path.read_text(encoding="utf-8"))


def _output_root() -> Path:
    return Path(__file__).resolve().parent.parent / "output"


# ======================================================= emit_language_files


def emit_language_files(addon_dir: Path, addon_version: str,
                        ra_name_suffix: str) -> None:
    """Write one strings.po per language under resources/language/."""
    lang_root = addon_dir / "resources" / "language"
    lang_root.mkdir(parents=True, exist_ok=True)

    for lang_code in langdata.LANGUAGES:
        lang_dir = lang_root / f"resource.language.{lang_code}"
        lang_dir.mkdir(parents=True, exist_ok=True)
        po = _render_po(lang_code, addon_version, ra_name_suffix)
        (lang_dir / "strings.po").write_text(po, encoding="utf-8")


def _render_po(lang_code: str, addon_version: str, ra_name_suffix: str) -> str:
    kodi_tag = _kodi_lang_tag(lang_code)
    header = _PO_HEADER.format(version=addon_version, lang=kodi_tag)
    body: list[str] = [header]
    for entry in langdata.entries():
        msgctxt = entry.ctx
        msgid = entry.text("en_gb", ra_name_suffix=ra_name_suffix)
        if lang_code == "en_gb":
            msgstr = ""
        else:
            msgstr = entry.text(lang_code, ra_name_suffix=ra_name_suffix)
        body.append(
            f'\nmsgctxt "{msgctxt}"\n'
            f'msgid "{_po_escape(msgid)}"\n'
            f'msgstr "{_po_escape(msgstr)}"\n'
        )
    return "".join(body)


def _po_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


_PO_HEADER = '''# XBMC Media Center language file
# Addon Name: RetroArch
# Addon version: {version}
msgid ""
msgstr ""
"Project-Id-Version: XBMC-Addons\\n"
"Report-Msgid-Bugs-To: https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/issues\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Language: {lang}\\n"
"Plural-Forms: nplurals=2; plural=(n != 1)\\n"
'''


# =================================================== customize_retroarch_cfg


# Path keys redirected at packaging time. The cfg ships with whatever Lakka
# built it with; we point it at addon-installed paths so RA looks at the
# right place on first launch (before firstrun.py runs).
_USER_CFG_DIRS = ("savefiles", "savestates", "remappings", "playlists", "thumbnails")
_RES_DIRS = (
    "system", "assets", "audio_filters", "video_filters", "joypads",
    "shaders", "database", "overlays",
)

# Misc retroarch.cfg pinned values.
_PINNED_VALUES: dict[str, str] = {
    "all_users_control_menu":         "true",
    "content_show_images":            "false",
    "content_show_music":             "false",
    "content_show_video":             "false",
    "input_menu_toggle_gamepad_combo": "4",
    "menu_driver":                    "xmb",
    "menu_swap_ok_cancel_buttons":    "true",
    "video_threaded":                 "false",
    "menu_core_enable":               "true",
    "xmb_alpha_factor":               "100",
    "video_driver":                   "glcore",
    "audio_driver":                   "openal",
}


def customize_retroarch_cfg(addon_dir: Path, addon_name: str) -> None:
    """Rewrite paths and pin a handful of settings inside the shipped cfg.

    Uses the same load/edit/save round-trip as the runtime — this avoids
    duplicating cfg parsing logic between the build and the runtime.
    """
    # Import lazily so build-time consumers don't need PYTHONPATH set up.
    import sys
    sys.path.insert(0, str(_output_root() / "lib"))
    from ra.ra_config import RetroArchConfig  # type: ignore[import-not-found]

    cfg_path = addon_dir / "config" / "retroarch.cfg"
    if not cfg_path.is_file():
        log.warning("package: no retroarch.cfg to customize at %s", cfg_path)
        return

    cfg = RetroArchConfig.load(cfg_path)

    user_cfg = "/storage/.config/retroarch"
    res_base = f"/storage/.kodi/addons/{addon_name}/resources"
    cores = f"/storage/.kodi/addons/{addon_name}/lib/libretro"

    # User-writable subdirs (live under ~/.config/retroarch).
    for sub in _USER_CFG_DIRS:
        cfg.redirect_path_suffix(sub, f"{user_cfg}/{sub}")
    # Read-only resources shipped inside the addon.
    for sub in _RES_DIRS:
        cfg.redirect_path_suffix(sub, f"{res_base}/{sub}")
    # `retroarch-assets` is the Lakka name; we land it as `assets`.
    cfg.redirect_path_suffix("retroarch-assets", f"{res_base}/assets")
    # Cores live under `lib/libretro/` inside the addon (no `/cores` suffix).
    cfg.redirect_path_suffix("cores", cores)

    for key, value in _PINNED_VALUES.items():
        cfg.set(key, value)

    cfg.save()


# ============================================================= zip & link ==


def create_archive(addon_dir: Path, build_dir: Path, archive_name: str) -> None:
    """Zip the addon dir; place the archive (+ a -LATEST symlink) in build/<name>/."""
    addon_name = addon_dir.name
    out_dir = build_dir / addon_name
    out_dir.mkdir(parents=True, exist_ok=True)

    archive_path = out_dir / archive_name
    if archive_path.exists():
        archive_path.unlink()

    _strip_hidden(addon_dir)
    # Use shell `zip` to preserve symlinks (`-y`). Python's zipfile module
    # stores symlinks as data, which breaks the SSL workaround set up at
    # first-run. The `-x` pattern excludes any remaining hidden entries.
    _run(
        ["zip", "-y", "-r", archive_name, addon_name, "-x", "*/.*"],
        cwd=str(addon_dir.parent), check=True,
    )
    shutil.move(str(addon_dir.parent / archive_name), str(archive_path))

    latest = out_dir / f"{addon_name}-LATEST.zip"
    latest.unlink(missing_ok=True)
    os.symlink(archive_name, latest)
    log.info("package: archive at %s", archive_path)


# ======================================================= updates.xml v2 ====

# GitHub release-asset base. Asset URLs are <base>/<tag>/<filename>, where the
# tag is the addon version string (e.g. v2.0.0).
_RELEASE_BASE = (
    "https://github.com/spleen1981/retroarch-kodi-addon-CoreELEC/releases/download"
)


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file (streamed, 1 MiB blocks)."""
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def emit_updates_current(dst: Path, *, addon_id: str, addon_version: str,
                         addon_zip: Path, addon_sha256: str,
                         artifacts: list[tuple[str, str, str, str]]) -> None:
    """Write `updates-v2-current.xml`: a per-build reference manifest.

    The build can compute everything it produced (version, asset filename → URL,
    sha256) but NOT the human-curated policy values (min OS version, the
    requires_addon/requires_appimage compatibility floor). Those are emitted as
    EMPTY placeholders (min_ver="", min="") for the maintainer to fill in when
    merging the fresh hashes into the committed, hand-curated `updates.xml`.

    This file is a build artifact — add it to .gitignore. It intentionally does
    NOT carry the legacy <latest> entries (those live only in the curated file).

    `artifacts` is a list of (platform, version, filename, sha256).
    """
    tag = addon_version
    lines: list[str] = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<!-- BUILD ARTIFACT — real sha256 hashes, EMPTY policy placeholders.",
        "     Fill min_ver / requires_* and merge into the committed updates.xml. -->",
        "<updates>",
    ]

    addon_url = f"{_RELEASE_BASE}/{tag}/{addon_zip.name}"
    lines += [
        f'  <addon id="{addon_id}" distro="coreelec">',
        f"    <version>{addon_version}</version>",
        f"    <download_url>{addon_url}</download_url>",
        f"    <sha256>{addon_sha256}</sha256>",
        '    <requires_appimage min=""/>',
        "  </addon>",
    ]

    for platform, version, filename, sha in artifacts:
        url = f"{_RELEASE_BASE}/{tag}/{filename}"
        lines += [
            f'  <appimage platform="{platform}" distro="coreelec" min_ver="">',
            f"    <version>{version}</version>",
            f"    <download_url>{url}</download_url>",
            f"    <sha256>{sha}</sha256>",
            '    <requires_addon min=""/>',
            "  </appimage>",
        ]

    lines.append("</updates>")
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("package: wrote %s", dst)
