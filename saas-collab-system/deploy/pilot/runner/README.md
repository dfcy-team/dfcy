# Pilot runner 主机安装模板

推荐在应用 VM 上使用 systemd 安装 runner。`install-runner.sh` 只安装
标准库服务、root-owned 固定桥接脚本、精确 sudoers 规则和 systemd 单元；
它不会生成 token、证书、OpenAI key、registry token 或候选 manifest。

## 安装与凭据准备

```sh
sudo bash deploy/pilot/runner/install-runner.sh
```

由 owner 另行准备以下文件（均为绝对路径、非符号链接）：

| 文件 | 建议 owner/mode | 用途 |
| --- | --- | --- |
| `/etc/saas-collab/runner/config.json` | `root:saas-runner 0640` | 非敏感 runner 配置 |
| `/etc/saas-collab/runner/secrets/runner.token` | `root:saas-runner 0440`（或 `0640`） | HTTPS Bearer token |
| `/etc/saas-collab/runner/tls/runner.crt` | `root:saas-runner 0440` | runner TLS 证书 |
| `/etc/saas-collab/runner/tls/runner.key` | `root:saas-runner 0440` | runner TLS 私钥 |
| `/etc/saas-collab/runner/approved-candidate.json` | `root:saas-runner 0440` | CI/架构员原子发布的候选摘要 |
| `/etc/saas-collab/runner/registry-token` | `root:root 0400`（或 `0600`） | 仅供 root 桥接 stdin 的短期 registry token |

证据目录 `/var/lib/saas-collab/pilot-runner/evidence` 为
`saas-runner:saas-runner 0700`。不要把这些 live 文件加入 Git 或镜像。

## 启停

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now saas-collab-pilot-runner
curl --cacert /etc/saas-collab/runner/tls/runner.crt \
  https://127.0.0.1:9444/healthz
```

运行服务没有 Docker socket、没有 `docker` 组权限。普通执行账户（默认
`dfcy01`）也不得属于 `docker` 组；production-baseline/runtime 会直接拒绝这种
现场状态，且不会自动改组。普通执行账户只被
sudoers 允许调用三个无参数 root-owned bridge；bridge 校验通用候选 manifest
的版本、父版本/父 SHA、release plan、镜像 digest、迁移摘要、CI 门禁证明、
actor/registry 用户和 token 文件，然后才调用现有 production-control。
`V2.44.59`（父版本 `V2.44.58`）只是本批次候选示例，不会固化到 runner
执行器逻辑中。CI/架构员须先用 `stage-approved-candidate.sh --source=...`
校验并原子发布该文件；生产控制当前账本的 `release_sha` 是父 SHA 的权威来源。

## 当前现场阻断项

当前外部 VM 地址 `192.168.2.10:8443` 可达，受控 SSH 入口是
`192.168.2.10:22131`；VM 内网地址 `192.168.174.131:22` 也可按现场配置使用。
`preflight-runner.sh` 默认只读检查 `192.168.2.10:22131`，不得把端口探测当成
授权或执行。现场若改用内网入口，应通过 `PILOT_VM_HOST`/
`PILOT_VM_SSH_PORT` 配置，不要修改脚本绕过检查。

另外，生产控制树、live env、backup hook 和 `config/baseline.sha256` 必须
root-owned、不可由 `dfcy01` 或 runner 用户写入；live env 必须声明
`PRODUCTION_REQUIRE_BACKUP=true` 及 root-owned 非符号链接 backup command。
若现场仍是部署用户可写或缺备份钩子，runtime preflight 必须失败。修复权限、
重新生成 baseline 并完成架构员门禁后再切换；本模板不会自动改权限、改用户组或
重启 VM。
