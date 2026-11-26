# Docker for this project: a beginner's guide

Docs only. Nothing in the project uses Docker today, and nothing here is implemented: no Dockerfile, no image, no
change to how the project runs. The background is in `cmds\conversation\2026-11-25.md` ("do we need Docker?"):

- not needed for `nli_label.py` now;
- recommended later for serving a translation model with vLLM (plan task 3);
- maybe later for identical setups on the 5 offline H200 machines.

**Every command on this page is an example to read, not run here.** Each block is marked that way. Versions are
written as `<version>`; section 4.1 says how to choose one. No passwords or keys appear on this page.

Contents:

1. The ideas, in plain words
2. Which parts of this project could use it
3. Is it allowed on the target machines? (checklist)
4. Offline: save, copy, load, and disk space
5. Worked example: Hunyuan-MT-7B with the official vLLM image
6. On the Windows PC (RTX 5090)
7. Common problems
8. Glossary and links

## 1. The ideas, in plain words

| Word | Meaning |
|---|---|
| **image** | A frozen, read-only package: a small Linux system + CUDA libraries + Python + every package + the program. Like an installer that never changes. |
| **container** | One running copy of an image. You can start, stop and delete it. Deleting it does not delete the image. Anything written inside a container is lost when the container is deleted, unless it was written to a volume. |
| **tag / version** | The part after the colon: `vllm/vllm-openai:<version>`. The same name with a different tag is a different image. `latest` just means "whatever was newest when you pulled", so it changes over time. |
| **volume** (here: a bind mount) | A folder of the machine shared with the container: `-v /data/models:/models` means "the machine's `/data/models` appears inside the container as `/models`". Models stay on the machine's disk, not inside the image. |
| **port** | A network door. `-p 8001:8000` means "the machine's port 8001 leads to port 8000 inside the container". Other programs talk to `http://<machine>:8001`. |
| **registry** | A server that stores images, e.g. Docker Hub. `docker pull` downloads from it. The H200 machines are offline, so they never pull; they load a `.tar` file instead (section 4). |

**Docker vs a Python venv.** A venv holds only Python packages. It still uses the machine's Python, system
libraries and (for torch wheels with CUDA) whatever driver is there. A Docker image holds everything above the
kernel and the GPU driver: its own Linux files, its own CUDA libraries, its own Python, its own torch. So two images
with different torch / CUDA versions never conflict with each other or with our venv. The cost: images are big
(gigabytes), and you need Docker installed and permission to use it.

**The NVIDIA Container Toolkit.** A plain container cannot see the GPUs. The toolkit is a small add-on on the
machine that, when you write `--gpus all`, passes the GPUs and the machine's driver into the container. The GPU
driver stays on the machine; the image brings only the CUDA libraries. So the machine's driver must be new enough
for the image's CUDA version.

One picture:

```
  machine (Ubuntu, 8 x H200, NVIDIA driver)
  |
  +-- Docker  (+ NVIDIA Container Toolkit)
        |
        +-- container  (from image vllm/vllm-openai:<version>)
              |  vLLM server listens on port 8000 inside
              |
              +-- GPU(s) ........ given by  --gpus all  /  --gpus '"device=0"'
              +-- /models ....... is the machine's folder /data/models   (-v /data/models:/models)
              +-- port 8000 ..... is the machine's port 8001             (-p 8001:8000)

  viewer / curl  --->  http://<machine>:8001/v1   --->  container port 8000
```

## 2. Which parts of this project could use it

| Part | Docker? | Why |
|---|---|---|
| `nli_label.py` runs on the H200 | **not now** (maybe later) | the venv + offline wheels work (`cmds\h200\linux_h200.md`, `pkgs\h200-ubuntu-py312`). Docker would help when 5 machines must have the identical setup, and once the setup stops changing |
| Translation model server (Hunyuan-MT-7B via vLLM, task 3) | **yes, recommended** | vLLM brings its own torch / CUDA versions that can conflict with nli_label's. The official image `vllm/vllm-openai` runs it in one command, OpenAI-compatible, without touching our venv |
| The viewer (FastAPI + built frontend) | no | runs on the Windows PC; nothing to gain |
| The model service (`nli_playground.py`) | no | same venv as nli_label |
| The Windows PC (RTX 5090) | only if needed | Docker Desktop on Windows runs inside WSL and keeps a growing disk file (the 70 GB `docker_data.vhdx` found on 2026-11-25) |

## 3. Is it allowed on the target machines? (checklist)

Run these on one H200 machine first. Example, not run here:

```bash
# 3.1 Is Docker installed?
docker --version
#   "Docker version 2x.y.z, build ..."   -> installed
#   "docker: command not found"           -> not installed; ask the admin (installing needs root)

# 3.2 Is the Docker service running?
systemctl is-active docker
#   "active"   -> running
#   "inactive" -> installed but stopped; ask the admin to start it

# 3.3 May I use it without sudo?
groups
#   the list contains "docker"            -> yes
docker info
#   prints a long report                  -> yes
#   "permission denied while trying to connect to the Docker daemon socket" -> not in the docker group
```

Note: being in the `docker` group is effectively root on that machine. On shared machines the admin may refuse it.
That is a normal answer, not an error.

```bash
# 3.4 Is the NVIDIA Container Toolkit installed?
nvidia-ctk --version
#   prints a version                      -> installed
#   "command not found"                   -> not installed

# 3.5 Can a container see the GPUs?  (needs an image that is already on the machine;
#     offline, load one first, see section 4. The vLLM image works for this too.)
docker run --rm --gpus all ubuntu nvidia-smi
#   the usual nvidia-smi table with 8 x H200 -> everything works
#   "could not select device driver "" with capabilities: [[gpu]]" -> the toolkit is missing or Docker was not
#                                             restarted after installing it (section 7)
```

Installing the toolkit is an admin job: install the `nvidia-container-toolkit` package, run
`sudo nvidia-ctk runtime configure --runtime=docker`, then `sudo systemctl restart docker` (see the NVIDIA guide
in section 8). Offline machines need the `.deb` packages copied in.

### 3.6 A shared cluster: Apptainer instead

If the machines are a shared cluster (for example with Slurm), Docker is often not allowed. **Apptainer** (formerly
Singularity) is used instead. Same idea, but it runs as your normal user, needs no service, and can use Docker
images. Example, not run here:

```bash
apptainer --version                                   # installed?

# turn a saved Docker image (.tar, section 4) into one Apptainer file (.sif)
apptainer build vllm.sif docker-archive://vllm.tar

# run it: --nv = GPUs, --bind = folder sharing (like -v)
apptainer exec --nv --bind /data/models:/models vllm.sif nvidia-smi
apptainer exec --nv --bind /data/models:/models vllm.sif \
    vllm serve /models/Hunyuan-MT-7B --served-model-name Hunyuan-MT-7B --port 8001
```

Differences to remember: there is no `-p` (the program listens directly on the machine's port, so pick a free one
with `--port`), and your home folder is visible inside by default.

| Docker | Apptainer |
|---|---|
| `docker load -i x.tar` | `apptainer build x.sif docker-archive://x.tar` |
| `--gpus all` | `--nv` |
| `-v /a:/b` | `--bind /a:/b` |
| `-p 8001:8000` | none; use the program's `--port 8001` |
| `docker ps` / `docker stop` | a normal process: `ps`, `kill`, or run inside `tmux` |

## 4. Offline: save, copy, load, and disk space

### 4.1 Choosing `<version>`

- Look at the tags of `vllm/vllm-openai` on Docker Hub and the vLLM release notes. Use a fixed version like
  `v0.x.y`, never `latest`, so all machines get the same thing.
- Hunyuan-MT-7B needs vLLM 0.10.0 or newer (the Hunyuan-MT GitHub page).
- The image's CUDA version must be supported by the machine's driver. Compare the driver's "CUDA Version" in
  `nvidia-smi` with the CUDA version in the vLLM release notes for that tag. The H200 and the RTX 5090 both need
  a recent CUDA (12.8 or newer is safe for the 5090).
- Write the chosen tag down in this file once chosen.

### 4.2 The steps

On a machine with internet and Docker. Example, not run here:

```bash
docker pull vllm/vllm-openai:<version>
docker save vllm/vllm-openai:<version> -o vllm-openai_<version>.tar
sha256sum vllm-openai_<version>.tar > vllm-openai_<version>.tar.sha256
```

Copy the `.tar`, the `.sha256` and the model folder (e.g. `Hunyuan-MT-7B\`, downloaded from Hugging Face) to the
H200 machine. Then, on the H200 machine. Example, not run here:

```bash
sha256sum -c vllm-openai_<version>.tar.sha256     # must print "OK"; otherwise copy again
docker load -i vllm-openai_<version>.tar          # prints "Loaded image: vllm/vllm-openai:<version>"
docker images                                     # the image is listed with its size
```

On Windows, the SHA-256 of a file: `Get-FileHash .\vllm-openai_<version>.tar -Algorithm SHA256`.

Do this once per machine (5 times for the H200s). The `.tar` can be deleted after loading.

### 4.3 Sizes to expect (rough; check with `docker images`)

| Item | Size |
|---|---|
| `vllm/vllm-openai` image | about 10-20 GB on disk, depending on the version; the `.tar` is about the same |
| `ubuntu` image (only for the GPU test) | under 100 MB |
| Hunyuan-MT-7B weights (bf16) | about 15 GB, kept outside the image in the models folder |

So plan for about 2 x the image size free during loading (the `.tar` + the loaded image), plus the model.

### 4.4 Where the disk space goes, and how to clean it

On Linux, Docker keeps everything under `/var/lib/docker`. Example, not run here:

```bash
docker system df          # space used by images, containers, volumes, build cache
docker ps -a              # all containers, also stopped ones (they still use disk)
docker image ls           # all images and their sizes

docker container prune    # delete stopped containers
docker image prune        # delete untagged ("dangling") images
docker system prune       # both, plus unused networks and build cache; asks for "y"
docker system prune -a    # also every image not used by a container: you must load them again (offline!)
```

Careful on offline machines: `prune -a` deletes the vLLM image if no container uses it at that moment, and it
cannot be pulled back without internet. Keep the `.tar` somewhere until you are sure.

On Windows, see section 6.3 (the WSL disk file).

## 5. Worked example: Hunyuan-MT-7B with the official vLLM image

Assumes: Docker + toolkit work (section 3), the image is loaded (section 4), and the model folder is at
`/data/models/Hunyuan-MT-7B` on the machine (the folder with `config.json` and the `.safetensors` files).

### 5.1 Start the server

Example, not run here:

```bash
docker run -d --name hunyuan-mt \
    --gpus '"device=0"' \
    --ipc=host \
    -p 8001:8000 \
    -v /data/models:/models:ro \
    -e HF_HUB_OFFLINE=1 \
    --restart unless-stopped \
    vllm/vllm-openai:<version> \
    --model /models/Hunyuan-MT-7B \
    --served-model-name Hunyuan-MT-7B \
    --trust-remote-code \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --gpu-memory-utilization 0.85
```

Line by line:

| Line | What it does |
|---|---|
| `docker run -d` | create and start a container; `-d` = in the background (you get your prompt back) |
| `--name hunyuan-mt` | a name, so later commands can say `hunyuan-mt` instead of a long ID |
| `--gpus '"device=0"'` | only GPU 0. The quotes are needed exactly like this. `--gpus all` gives all 8; a 7B model needs one |
| `--ipc=host` | lets the container use the machine's shared memory. vLLM (PyTorch) needs it; without it, it can crash. The alternative is `--shm-size=16g` |
| `-p 8001:8000` | the machine's port 8001 leads to vLLM's port 8000 inside the container |
| `-v /data/models:/models:ro` | the machine's models folder appears as `/models` inside; `:ro` = read-only, the container cannot change it |
| `-e HF_HUB_OFFLINE=1` | tells the Hugging Face library not to try the internet (the machine is offline anyway; this avoids waiting for timeouts) |
| `--restart unless-stopped` | start again after a reboot or crash, unless you stopped it yourself. Leave it out while testing |
| `vllm/vllm-openai:<version>` | the image. **Everything after this line goes to vLLM, not to Docker** |
| `--model /models/Hunyuan-MT-7B` | the model path **inside** the container (`/models`, not `/data/models`) |
| `--served-model-name Hunyuan-MT-7B` | the name clients must send as `"model"`. Must match the viewer's setting (5.4) |
| `--trust-remote-code` | allows code shipped with the model, as the Hunyuan-MT GitHub page does; harmless if not needed |
| `--dtype bfloat16` | the model's own precision |
| `--max-model-len 8192` | the longest prompt + answer in tokens. Smaller = less GPU memory. A paragraph translation needs far less |
| `--gpu-memory-utilization 0.85` | vLLM takes this share of the GPU's memory up front (default 0.9). Lower it if nli_label should share the GPU |

Loading takes one to a few minutes. Watch it with `docker logs -f hunyuan-mt` (Ctrl+C stops watching, not the
server). It is ready when the log shows the server listening (e.g. "Uvicorn running on http://0.0.0.0:8000" /
"Application startup complete").

### 5.2 Check it

From the same machine use `localhost`; from another machine use the machine's name or IP. Example, not run here:

```bash
curl http://localhost:8001/v1/models
#   {"object":"list","data":[{"id":"Hunyuan-MT-7B", ...}]}    -> the server is up; "id" is the name to use

curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "model": "Hunyuan-MT-7B",
        "messages": [{"role": "user",
                      "content": "Translate the following segment into English, without additional explanation.\n\nDas Wetter ist heute schön."}],
        "temperature": 0.7, "top_p": 0.6, "top_k": 20, "repetition_penalty": 1.05,
        "max_tokens": 256
      }'
#   the answer is in choices[0].message.content: "The weather is nice today."
```

The prompt wording and the sampling values (`top_k` 20, `top_p` 0.6, `repetition_penalty` 1.05, `temperature` 0.7)
are the ones on the Hunyuan-MT-7B model card. For Chinese ↔ other languages the card uses a Chinese prompt instead
(`把下面的文本翻译成<target_language>，不要额外解释。`). The viewer's `"prompt": "hunyuan"` setting is meant to do this
wording for you.

On Windows PowerShell, `curl` may be an alias of `Invoke-WebRequest`; use `curl.exe` instead.

### 5.3 Stop, restart, logs

Example, not run here:

```bash
docker ps                      # running containers: name, image, ports ("0.0.0.0:8001->8000/tcp"), status
docker ps -a                   # also stopped ones
docker logs hunyuan-mt         # everything the server printed
docker logs -f --tail 50 hunyuan-mt   # the last 50 lines, then keep following
docker stop hunyuan-mt         # stop (GPU memory is freed)
docker start hunyuan-mt        # start the same container again, same settings
docker rm hunyuan-mt           # delete the stopped container (the image and the models stay)
```

To change a setting (port, GPU, model), `docker rm` the container and `docker run` again with the new settings.

### 5.4 How the viewer's translation setting points to it

The viewer's translation feature (task 3) reads a provider entry from `viewer_config.json`:

```json
{"name": "hunyuan", "kind": "openai", "base_url": "http://127.0.0.1:8001/v1",
 "model": "Hunyuan-MT-7B", "prompt": "hunyuan", "timeout": 120}
```

| Setting | Comes from |
|---|---|
| `"kind": "openai"` | vLLM speaks the OpenAI API (`/v1/models`, `/v1/chat/completions`) |
| `"base_url"` host `127.0.0.1` | the server runs on the same computer as the viewer. If it runs on an H200 machine, use that machine's name or IP instead, and make sure the port is reachable (firewall) |
| `"base_url"` port `8001` | the **left** number of `-p 8001:8000` (the machine's port), not the 8000 inside |
| `"base_url"` ending `/v1` | the OpenAI path prefix; the viewer adds `/chat/completions` |
| `"model": "Hunyuan-MT-7B"` | exactly the `--served-model-name`; check with `curl .../v1/models` |
| `"prompt": "hunyuan"` | the viewer's prompt wording for Hunyuan-MT (5.2); not a Docker setting |
| `"timeout": 120` | seconds the viewer waits for one answer; the first request after start can be slow |

No API key is needed: the vLLM server above was started without `--api-key`. Do not put real keys in
`viewer_config.json` that is committed to git.

## 6. On the Windows PC (RTX 5090)

### 6.1 How it works

Docker on Windows = **Docker Desktop**. It runs Linux containers inside **WSL2** (a small Linux virtual machine built
into Windows). Install from docs.docker.com ("Install Docker Desktop on Windows"), choose the WSL 2 backend. It
needs admin rights once, and a restart.

### 6.2 GPU support

With WSL2, a current NVIDIA Windows driver and a current Docker Desktop, `--gpus all` works without installing the
toolkit yourself. Check (example, not run here):

```powershell
wsl --status                                   # "Default Version: 2"
docker run --rm --gpus all ubuntu nvidia-smi   # should show the RTX 5090
```

Model paths on Windows: `-v D:\models:/models` works in PowerShell. Reading model files from a Windows drive through
WSL is slower than from inside WSL; for a 15 GB model this mainly makes the first start slower.

The RTX 5090 has 32 GB. Hunyuan-MT-7B in bf16 (~15 GB) fits, but not together with other large GPU work; lower
`--gpu-memory-utilization` or stop the container while running nli_label.

### 6.3 The disk file that grows (the 70 GB `docker_data.vhdx`)

Docker Desktop keeps all images and containers inside one virtual disk file. On 2026-11-25 this file was found at
70 GB under AppData. The file **grows but never shrinks by itself**, even after deleting images.

Find it (example, not run here):

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Docker" -Recurse -Filter *.vhdx -ErrorAction SilentlyContinue |
    Select-Object FullName, @{n='GB';e={[math]::Round($_.Length/1GB,1)}}
# usually  %LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx  (older versions: ...\wsl\data\ext4.vhdx)
```

Free space inside it first, then shrink the file. Example, not run here:

```powershell
# 1. Inside Docker: delete what is not needed (see 4.4)
docker system df
docker system prune            # or: docker system prune -a   (every unused image is gone)

# 2. Stop Docker Desktop (tray icon > Quit), then stop WSL completely
wsl --shutdown

# 3a. Shrink with diskpart (works on Windows 10 Pro/Home; admin PowerShell)
diskpart
#   select vdisk file="C:\Users\<you>\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
#   attach vdisk readonly
#   compact vdisk
#   detach vdisk
#   exit

# 3b. Or, if the Hyper-V PowerShell module is installed (admin PowerShell):
Optimize-VHD -Path "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx" -Mode Full
```

Cautions:
- Quit Docker Desktop and run `wsl --shutdown` first; never compact a disk that is in use.
- Compacting only gives back space that was freed inside (step 1). Without pruning first, it saves little.
- `wsl --shutdown` stops **every** WSL distribution, not just Docker. Save work in WSL first.
- If the file is only big because of images you still want, it will not get smaller.
- Easiest alternative: Docker Desktop > Troubleshoot > "Clean / Purge data" deletes everything (all images and
  containers) and starts with a small file. Only if nothing in it is needed.
- Docker Desktop settings (Resources > Advanced) can move the disk image to another drive (e.g. `D:`), so `C:` does
  not fill up.

### 6.4 When not to use it on this PC

- For the viewer, `nli_label.py`, `nli_playground.py`: no, the venv is simpler (section 2).
- When `C:` is short of space: the disk file grows with every image (the vLLM image alone is 10-20 GB).
- When you only want to try a translation once: a hosted API or a quick test elsewhere costs less setup.
- Use it when you want to test the exact vLLM server that will run on the H200s, before copying the `.tar` there.
- If Docker Desktop is installed but not used, quitting it (and turning off "Start when you sign in") frees memory.

## 7. Common problems

| Message / symptom | Cause | Fix |
|---|---|---|
| `could not select device driver "" with capabilities: [[gpu]]` | the NVIDIA Container Toolkit is missing, or Docker was not restarted after installing it | admin: install the toolkit, `sudo nvidia-ctk runtime configure --runtime=docker`, `sudo systemctl restart docker` (section 3) |
| `Bind for 0.0.0.0:8001 failed: port is already allocated` / `address already in use` | another container or program uses port 8001 | `docker ps` (an old container?) and `ss -ltnp \| grep 8001` (Linux) / `netstat -ano \| findstr 8001` (Windows); stop it or use another left-hand port, e.g. `-p 8002:8000`, and change `base_url` |
| `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock` | your user is not in the `docker` group | ask the admin (`sudo usermod -aG docker <user>`, then log out and in), or use `sudo docker ...` if allowed, or Apptainer |
| `no space left on device` while loading or running | `/var/lib/docker` (Linux) or the WSL disk (Windows) is full | `docker system df`, prune (4.4); delete the `.tar` after loading; on Windows section 6.3 |
| vLLM log: model path not found / `config.json` missing | the `-v` left side is wrong, or `--model` uses the machine path instead of the container path | `docker run --rm -v /data/models:/models --entrypoint ls vllm/vllm-openai:<version> -l /models` must list `Hunyuan-MT-7B`; then `--model /models/Hunyuan-MT-7B` |
| vLLM tries to download from huggingface.co | `--model` is a Hub name (`tencent/...`) instead of a local path | use the local path and `-e HF_HUB_OFFLINE=1` |
| `CUDA out of memory` at start | the GPU is used by something else, or `--max-model-len` is large | pick a free GPU (`nvidia-smi`), lower `--max-model-len`, adjust `--gpu-memory-utilization` |
| `CUDA driver version is insufficient` | the image's CUDA is newer than the machine's driver supports | choose an older `<version>` (4.1) or update the driver |
| crash mentioning shared memory / `/dev/shm` | `--ipc=host` (or `--shm-size`) is missing | add `--ipc=host` |
| viewer: connection refused / timeout | wrong host or port in `base_url`, server still loading, or a firewall | `curl <base_url>/models` from the viewer's computer; `docker logs hunyuan-mt` |
| viewer: `model ... does not exist` (404) | `"model"` differs from `--served-model-name` | make them identical |

## 8. Glossary and links

| Word | Meaning |
|---|---|
| Docker Engine / daemon | the background service on Linux that runs containers (`dockerd`) |
| Docker Desktop | the Windows / Mac app that runs Docker Engine inside a small Linux VM (WSL2 on Windows) |
| image, container, tag, volume, port, registry | section 1 |
| Docker Hub | the default public registry (`hub.docker.com`) |
| `docker save` / `docker load` | write an image to a `.tar` file / read it back; the offline way to move images |
| NVIDIA Container Toolkit | the add-on that gives containers the GPUs (`--gpus`) |
| WSL2 | Windows Subsystem for Linux, version 2: a real Linux kernel in a light VM |
| `.vhdx` | the virtual disk file WSL2 / Docker Desktop keeps their Linux files in |
| Apptainer (Singularity) | a container tool for shared clusters; runs as a normal user, can use Docker images; `.sif` files |
| vLLM | a fast server for large language models; `vllm/vllm-openai` is its official image with an OpenAI-compatible API |
| OpenAI-compatible | answers the same URLs and JSON as the OpenAI API (`/v1/chat/completions`), so any OpenAI client can use it |
| bind mount | `-v /machine/folder:/container/folder`: the kind of volume used on this page |

Official docs:

- Docker overview: https://docs.docker.com/get-started/docker-overview/
- Install Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Linux post-install (the `docker` group): https://docs.docker.com/engine/install/linux-postinstall/
- `docker save` / `docker load`: https://docs.docker.com/reference/cli/docker/image/save/ ,
  https://docs.docker.com/reference/cli/docker/image/load/
- Pruning (`docker system prune`): https://docs.docker.com/engine/manage-resources/pruning/
- Docker Desktop on Windows: https://docs.docker.com/desktop/setup/install/windows-install/
- Docker Desktop GPU support (WSL2): https://docs.docker.com/desktop/features/gpu/
- NVIDIA Container Toolkit install guide:
  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
- NVIDIA sample workload (the `nvidia-smi` test):
  https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/sample-workload.html
- vLLM with Docker: https://docs.vllm.ai/en/latest/deployment/docker.html
- vLLM OpenAI-compatible server: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
- Apptainer user guide: https://apptainer.org/docs/user/latest/
- Hunyuan-MT-7B model card: https://huggingface.co/tencent/Hunyuan-MT-7B
- Hunyuan-MT GitHub (vLLM serving, vLLM >= 0.10.0): https://github.com/Tencent-Hunyuan/Hunyuan-MT
- Shrinking a WSL disk: https://learn.microsoft.com/en-us/windows/wsl/disk-space
