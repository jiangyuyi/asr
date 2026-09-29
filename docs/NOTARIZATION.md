# macOS 签名与公证（可选）

## 为什么需要

从 GitHub Release 下载的压缩包会被 macOS 打上 `com.apple.quarantine` 标记。
未签名的程序在带标记状态下**不允许加载自己的动态库**，PyInstaller 打包的产物里
全是 dylib（Python 运行时、Qt），所以会直接失败：

```
Failed to load Python shared library '.../_internal/Python':
  ... not valid for use in process: library load disallowed by system policy
```

这不是程序 bug，是 Gatekeeper 的正常策略。

## 现在就能用（无需任何配置）

macOS 压缩包里附带一个 **`Open asr-mm.command`**，双击即可：

- 它会检测隔离标记，执行 `xattr -cr` 清除，然后启动程序
- 清除之后整个目录就不再受限，之后直接双击 `asr-mm-gui` 即可
- 同目录还有 `README-macOS.txt`，中英日三语说明

命令行用户可以手动执行：

```bash
xattr -cr ~/Downloads/asr-mm-gui
./asr-mm-gui/asr-mm-gui
```

或者在 Finder 里**右键 → 打开**（不是双击），再点「打开」。

## 彻底解决（需要付费 Apple 开发者账号）

只有 **Developer ID 签名 + Apple 公证（notarization）** 才能让下载的产物
双击即开、没有任何系统提示。这需要：

1. [Apple Developer Program](https://developer.apple.com/programs/) 会员（$99/年，个人账号即可）
2. 在 Xcode 或「钥匙串访问」中创建 **Developer ID Application** 证书，
   导出为 `.p12` 并设密码
3. 在 App Store Connect → Users and Access → Integrations 创建
   **App Store Connect API Key**，下载 `.p8` 私钥，记下 Key ID 和 Issuer ID

然后在仓库 **Settings → Secrets and variables → Actions** 添加 6 个 secret：

| Secret | 内容 |
|---|---|
| `MACOS_CERT_P12` | `.p12` 文件的 base64（`base64 -i cert.p12` 的输出） |
| `MACOS_CERT_PASSWORD` | 导出 `.p12` 时设的密码 |
| `MACOS_KEYCHAIN_PASSWORD` | 任意临时密码即可 |
| `NOTARY_KEY_ID` | API Key 的 Key ID |
| `NOTARY_ISSUER_ID` | API Key 的 Issuer ID |
| `NOTARY_PRIVATE_KEY` | `.p8` 私钥文件的完整内容 |

流水线会自动检测这些 secret：

- **已配置** → 签名并公证，产物双击即开
- **未配置** → 跳过签名，附带 `Open asr-mm.command` 启动器（见上）

签名逻辑在 `packaging/sign_macos.sh`，构建入口在 `.github/workflows/release.yml`。

## 本地手动签名

```bash
codesign --force --deep --options runtime \
  --sign "Developer ID Application: Your Name (TEAMID)" \
  dist/asr-mm-gui
codesign --verify --deep --strict --verbose=2 dist/asr-mm-gui
```
