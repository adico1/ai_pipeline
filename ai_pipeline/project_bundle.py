"""Manifest-verified source bundles for projects containing multiple files."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

EXCLUDED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'node_modules'}
ALLOWED_SUFFIXES = {'.py', '.toml', '.md', '.txt', '.json', '.yaml', '.yml'}


def validate_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or '..' in path.parts or '\\' in name:
        raise ValueError(f'Unsafe bundle path: {name}')
    if any(part in EXCLUDED or part.startswith('.env') or any(word in part.lower() for word in ('secret', 'credential', 'private_key')) for part in path.parts):
        raise ValueError(f'Excluded bundle path: {name}')
    if path.name != '.gitignore' and path.suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f'Unsupported source file: {name}')
    return path


def source_files(workspace, includes):
    """Collect explicit source roots; reject links and runtime/data artifacts."""
    workspace = Path(workspace)
    files = {}
    for include in includes:
        relative = PurePosixPath(include)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Includes must be relative source paths')
        root = workspace / include
        if not root.exists():
            raise ValueError(f'Missing release input: {include}')
        for path in ([root] if root.is_file() else sorted(root.rglob('*'))):
            name = path.relative_to(workspace).as_posix()
            if any(part in EXCLUDED for part in PurePosixPath(name).parts):
                continue
            if any((workspace / Path(*PurePosixPath(name).parts[:i])).is_symlink() for i in range(1, len(PurePosixPath(name).parts) + 1)):
                raise ValueError(f'Symlinks cannot be bundled: {name}')
            if path.is_dir():
                continue
            validate_path(name)
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError('Cannot bundle an empty project')
    return dict(sorted(files.items()))


def build_bundle(workspace, output, includes):
    files = source_files(workspace, includes)
    archive = Path(output) / 'project.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in files:
            bundle.write(Path(workspace) / name, name)
    manifest = {'files': files, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
    (Path(output) / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


def install_bundle(release, destination):
    """Verify every entry before writing; never use unrestricted extractall."""
    release, destination = Path(release), Path(destination)
    manifest = json.loads((release / 'manifest.json').read_text())
    archive = release / 'project.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['archive_sha256']:
        raise ValueError('Archive digest mismatch')
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != set(manifest['files']):
            raise ValueError('Archive entries differ from manifest')
        contents = {}
        for name in names:
            validate_path(name)
            content = bundle.read(name)
            if hashlib.sha256(content).hexdigest() != manifest['files'][name]:
                raise ValueError(f'Source digest mismatch: {name}')
            contents[name] = content
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in contents.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return manifest
