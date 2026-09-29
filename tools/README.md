# tools/

开发与验证脚本。都不参与运行时依赖，也不需要安装。

## 复现 Phase 0 的模型选型

`phase0_*.py` 是最初用来横向对比三个模型的探针，README 里的准确率与速度数据
都来自这组脚本。它们按最初的机器写成，路径是硬编码的 Windows 路径，要复现需先改：

```python
ROOT = r"D:\Work\asr_mm"     # 改成你自己的项目根目录
```

前置条件：`vendor/models/` 下放好对应 GGUF 模型，`vendor/avx2/` 下放好
FunASR llama.cpp 运行时（`packaging/prepare_payload.py --target win` 会下载）。

| 脚本 | 作用 |
|---|---|
| `phase0_validate.py` | 抽音频、跑 Paraformer / SenseVoice、对比子区间与全片 |
| `phase0b_compare.py` | 扫描 `--vad-maxseg` 各档，观察时间戳粒度对准确率的影响 |
| `phase0c_nano.py` | Nano 的标点能力，以及长噪声段上的复读退化 |
| `phase0d_slice.py` | 主场景（截取区间）下 Nano 与 Paraformer 的对比 |

## 端到端测试

需要先跑过 `asr-mm setup` 下载模型。

| 脚本 | 作用 |
|---|---|
| `run_cli.py` | 把 `asr-mm` 子进程输出写进 UTF-8 日志，绕开 Windows 控制台代码页 |
| `e2e_test.py` | 11 项 CLI 端到端：选区、时间码、预读、导出、报错路径 |
| `dist_test.py` | 验证打包产物能解析内置运行时/ffmpeg 并完成转写 |
| `verify_dist.py` | 比对打包产物与源码运行的输出是否逐字一致 |
| `gui_smoke.py` | 驱动真实窗口：加载视频、跑一次识别、截图 |
| `ffutil.py` | ffmpeg 调用封装 |

## 打包

| 脚本 | 作用 |
|---|---|
| `../packaging/prepare_payload.py` | 准备引擎运行时与 ffmpeg（按目标平台） |
| `../packaging/make_archives.py` | 打包 release 归档 |
| `run_gui.py` | 启动 `dist/asr-mm-gui/` 里的图形界面（附带产物完整性检查） |
| `package_local.sh` | 本地出一份 Windows 归档 |
| `check_archive.sh` | 解压归档并运行，确认产物可用 |

## 发布

| 脚本 | 作用 |
|---|---|
| `watch_ci.sh` | 轮询 release 流水线直到结束 |
| `verify_release.sh` | 检查 release 状态、资产大小与下载链接 |
| `download_and_verify.sh` | 把资产下载回来并实际运行（Windows），校验架构（macOS） |
