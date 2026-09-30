"""Append the network-settings vocabulary to all three catalogs.

Kept separate from i18n.py so the big dictionary stays readable; the module is
imported at the bottom of i18n.py so CATALOGS is complete before any lookup.
"""
from __future__ import annotations

ZH: dict[str, str] = {
    "net.title": "网络设置",
    "net.intro": ("模型从 Hugging Face 或 ModelScope 下载。如果公司网络使用 TLS "
                 "解密代理，浏览器能正常访问但程序可能报证书错误，"
                 "可在这里指定公司根证书或切换下载源。"),
    "net.mirror": "下载源",
    "net.mirror_auto": "自动（Hugging Face 优先，失败换 ModelScope）",
    "net.mirror_hf": "仅 Hugging Face",
    "net.mirror_ms": "仅 ModelScope（国内推荐）",
    "net.ca_bundle": "公司根证书文件",
    "net.ca_browse": "选择…",
    "net.ca_clear": "清除",
    "net.ca_none": "未指定（使用系统信任库）",
    "net.ca_ok": "已指定：{path}",
    "net.ca_bad": "不可用：{error}",
    "net.insecure": "跳过 TLS 校验（不推荐）",
    "net.insecure_tip": ("仅在网络确实拦截且无法提供根证书时勾选。"
                      "这会失去对下载内容的身份验证，模型文件相当于可执行内容，"
                      "请只在你信任的网络下使用。"),
    "net.trust": "证书来源：{source}",
    "net.test": "测试连接",
    "net.testing": "正在测试…",
    "net.save": "保存",
    "net.cancel": "取消",
    "net.status_ok": "{label}：正常",
    "net.status_fail": "{label}：{reason}",
    "net.host": "主机",
    "net.issuer": "签发者",
    "net.verdict": "判断",
    "net.diag_title": "网络诊断",
    "net.diag_empty": "没有任何下载源可用。",
    "net.settings_path": "设置文件：{path}",
    "dlg.dl_failed": "下载失败：{name}",
    "dlg.dl_ssl_help": (
        "如果浏览器可以正常打开这些网站，多半是公司网络的 TLS 解密代理：\n"
        "  · 打开「工具 → 网络设置」，点「测试连接」看诊断结果\n"
        "  · 若诊断显示证书被企业设备签发，下载该代理的根证书并指定给它\n"
        "  · 或改用「仅 ModelScope」下载源\n"
        "  · 实在拿不到根证书，才考虑「跳过 TLS 校验」"),
    "dlg.dl_mirror_help": (
        "所有下载源都不可用。可以试试：\n"
        "  · 切换网络或使用代理\n"
        "  · 在「工具 → 网络设置」里改用 ModelScope 镜像\n"
        "  · 稍后重试，服务器可能只是暂时过载"),
    "net.insecure_warn": (
        "警告：已关闭证书校验。\n\n"
        "这意味着无法确认下载到的文件是否来自 Hugging Face / ModelScope。"
        "模型权重等同于可执行内容，在被中间人替换的网络上存在风险。\n\n"
        "只在你信任的网络下使用此选项。"),
    "cli.net.help": "测试下载源与证书是否可用",
    "cli.net.title": "asr-mm {version} 网络诊断\n",
    "cli.net.summary": "汇总",
    "cli.net.all_ok": "所有下载源均可用。",
    "cli.net.some_fail": "{count} 个下载源不可用。",
    "cli.mirror.set": "下载源已设为 {value}",
    "cli.insecure.on": "已开启跳过 TLS 校验（不推荐）",
    "cli.insecure.off": "已关闭跳过 TLS 校验",
    "cli.ca.set": "根证书已设为 {path}",
    "cli.ca.cleared": "已清除根证书设置",
    "cli.settings_saved": "网络设置已保存",
}

EN: dict[str, str] = {
    "net.title": "Network settings",
    "net.intro": ("Models are downloaded from Hugging Face or ModelScope. If your "
                 "network inspects TLS, browsers will work but this program may "
                 "reject the certificate. Point it at your organisation's root "
                 "certificate here, or switch the download source."),
    "net.mirror": "Download source",
    "net.mirror_auto": "Automatic (Hugging Face first, then ModelScope)",
    "net.mirror_hf": "Hugging Face only",
    "net.mirror_ms": "ModelScope only (recommended in China)",
    "net.ca_bundle": "Organisation root certificate",
    "net.ca_browse": "Choose…",
    "net.ca_clear": "Clear",
    "net.ca_none": "none — using the system trust store",
    "net.ca_ok": "set: {path}",
    "net.ca_bad": "unusable: {error}",
    "net.insecure": "Skip TLS verification (not recommended)",
    "net.insecure_tip": ("Only for a network that inspects TLS and offers no "
                      "exportable root. It removes authentication of the "
                      "download; model weights are executable content, so use it "
                      "only on a network you trust."),
    "net.trust": "Certificate sources: {source}",
    "net.test": "Test connection",
    "net.testing": "Testing…",
    "net.save": "Save",
    "net.cancel": "Cancel",
    "net.status_ok": "{label}: OK",
    "net.status_fail": "{label}: {reason}",
    "net.host": "Host",
    "net.issuer": "Issuer",
    "net.verdict": "Verdict",
    "net.diag_title": "Network diagnostics",
    "net.diag_empty": "No download source is reachable.",
    "net.settings_path": "Settings file: {path}",
    "dlg.dl_failed": "Download failed: {name}",
    "dlg.dl_ssl_help": (
        "If your browser opens these sites fine, your network most likely "
        "inspects TLS:\n"
        "  · Open “Tools → Network settings” and press “Test connection”\n"
        "  · If the diagnosis shows a certificate issued by your organisation's "
        "appliance, download that root certificate and point this setting at it\n"
        "  · Or switch to the ModelScope source\n"
        "  · Only if you truly cannot obtain the root, consider skipping "
        "verification"),
    "dlg.dl_mirror_help": (
        "No source was reachable. Try:\n"
        "  · a different network, or a proxy\n"
        "  · switching to the ModelScope mirror in “Tools → Network settings”\n"
        "  · retrying later, the server may just be busy"),
    "net.insecure_warn": (
        "Warning: certificate verification is disabled.\n\n"
        "This program can no longer confirm the files came from Hugging Face or "
        "ModelScope. Model weights are executable content, so a network that "
        "replaces them in transit is a real risk.\n\n"
        "Use this option only on a network you trust."),
    "cli.net.help": "test whether the download sources and certificates work",
    "cli.net.title": "asr-mm {version} network diagnostics\n",
    "cli.net.summary": "Summary",
    "cli.net.all_ok": "All download sources are reachable.",
    "cli.net.some_fail": "{count} source(s) unreachable.",
    "cli.mirror.set": "Download source set to {value}",
    "cli.insecure.on": "TLS verification disabled (not recommended)",
    "cli.insecure.off": "TLS verification re-enabled",
    "cli.ca.set": "Root certificate set to {path}",
    "cli.ca.cleared": "Root certificate setting cleared",
    "cli.settings_saved": "Network settings saved",
}

JA: dict[str, str] = {
    "net.title": "ネットワーク設定",
    "net.intro": ("モデルは Hugging Face または ModelScope からダウンロードします。"
                 "社内ネットワークで TLS を復号するプロキシを使っている場合、"
                 "ブラウザでは開けてもこのプログラムは証明書を拒否することがあります。"
                 "ここで 루ート証明書を指定するか、ダウンロード元を変更してください。"),
    "net.mirror": "ダウンロード元",
    "net.mirror_auto": "自動（Hugging Face を優先し、失敗時は ModelScope）",
    "net.mirror_hf": "Hugging Face のみ",
    "net.mirror_ms": "ModelScope のみ（中国国内で推奨）",
    "net.ca_bundle": "会社のルート証明書",
    "net.ca_browse": "選択…",
    "net.ca_clear": "クリア",
    "net.ca_none": "未指定（システムの信頼ストアを使用）",
    "net.ca_ok": "指定済み: {path}",
    "net.ca_bad": "使用できません: {error}",
    "net.insecure": "TLS 検証をスキップ（非推奨）",
    "net.insecure_tip": ("TLS を復号するネットワークで 루ート証明書が提供できない場合のみ"
                      "使用してください。ダウンロード元の同一性を確認できなくなります。"
                      "モデルの重みは実行可能な内容なので、信頼できるネットワークでのみ"
                      "使用してください。"),
    "net.trust": "証明書の供給元: {source}",
    "net.test": "接続テスト",
    "net.testing": "テスト中…",
    "net.save": "保存",
    "net.cancel": "キャンセル",
    "net.status_ok": "{label}: 正常",
    "net.status_fail": "{label}: {reason}",
    "net.host": "ホスト",
    "net.issuer": "発行者",
    "net.verdict": "判定",
    "net.diag_title": "ネットワーク診断",
    "net.diag_empty": "利用可能なダウンロード元がありません。",
    "net.settings_path": "設定ファイル: {path}",
    "dlg.dl_failed": "ダウンロードに失敗しました: {name}",
    "dlg.dl_ssl_help": (
        "ブラウザでこれらのサイトを開ける場合、社内ネットワークが TLS を"
        "復号している可能性が高くなります:\n"
        "  · 「ツール → ネットワーク設定」を開き「接続テスト」を実行\n"
        "  · 診断で社内機器が発行した証明書と表示された場合、そのルート証明書を"
        "入手して指定してください\n"
        "  · または ModelScope をダウンロード元に使用します\n"
        "  · ルート証明書がどうしても入手できない場合のみ、検証のスキップを"
        "検討してください"),
    "dlg.dl_mirror_help": (
        "すべてのダウンロード元が利用できませんでした:\n"
        "  · ネットワークを切り替えるかプロキシを使用\n"
        "  · 「ツール → ネットワーク設定」で ModelScope に変更\n"
        "  · しばらく待って再試行（サーバー側の一時的な混雑の可能性）"),
    "net.insecure_warn": (
        "警告: 証明書の検証を無効にしています。\n\n"
        "ダウンロードしたファイルが Hugging Face / ModelScope 由来であることを"
        "確認できません。モデルの重みは実行可能な内容であり、転送中に差し替えられた"
        "場合のリスクがあります。\n\n"
        "この設定は信頼できるネットワークでのみ使用してください。"),
    "cli.net.help": "ダウンロード元と証明書が正常かテスト",
    "cli.net.title": "asr-mm {version} ネットワーク診断\n",
    "cli.net.summary": "まとめ",
    "cli.net.all_ok": "すべてのダウンロード元が利用可能です。",
    "cli.net.some_fail": "{count} 件のダウンロード元が利用できません。",
    "cli.mirror.set": "ダウンロード元を {value} に設定しました",
    "cli.insecure.on": "TLS 検証を無効にしました（非推奨）",
    "cli.insecure.off": "TLS 検証を有効に戻しました",
    "cli.ca.set": "ルート証明書を {path} に設定しました",
    "cli.ca.cleared": "ルート証明書の設定を解除しました",
    "cli.settings_saved": "ネットワーク設定を保存しました",
}
