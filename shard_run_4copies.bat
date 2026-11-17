@echo off
rem made by shard_commands.py: 4 copies on cuda:0, cuda:1
rem command: python shard_commands.py "D:\my corpus" --output-dir D:\hkc\tools --gpus 2 --copies-per-gpu 2 --shell cmd -- --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768 --country Germany
rem note: --write-split not given: only the decisions are written, not the kept / filtered lines (fine for tests; with it, about as much disk again as the corpus)
rem note: input D:\my corpus does not exist on this machine (fine if the commands run elsewhere)
if not exist D:\hkc\tools\logs mkdir D:\hkc\tools\logs
start "shard 0/4 cuda:0" /min cmd /c python nli_filter.py "D:\my corpus" --device cuda:0 --shard 0/4 --output-dir D:\hkc\tools --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768 --country Germany ^> D:\hkc\tools\logs\shard-0.log 2^>^&1
start "shard 1/4 cuda:1" /min cmd /c python nli_filter.py "D:\my corpus" --device cuda:1 --shard 1/4 --output-dir D:\hkc\tools --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768 --country Germany ^> D:\hkc\tools\logs\shard-1.log 2^>^&1
start "shard 2/4 cuda:0" /min cmd /c python nli_filter.py "D:\my corpus" --device cuda:0 --shard 2/4 --output-dir D:\hkc\tools --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768 --country Germany ^> D:\hkc\tools\logs\shard-2.log 2^>^&1
start "shard 3/4 cuda:1" /min cmd /c python nli_filter.py "D:\my corpus" --device cuda:1 --shard 3/4 --output-dir D:\hkc\tools --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768 --country Germany ^> D:\hkc\tools\logs\shard-3.log 2^>^&1
echo 4 copies started in their own (minimised) windows; logs: D:\hkc\tools\logs
echo When all windows have closed, run:
echo   python nli_filter.py --report --output-dir D:\hkc\tools
