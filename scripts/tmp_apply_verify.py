# -*- coding: utf-8 -*-
"""临时脚本：部署后应用 k8s yaml、验证 gzip/缓存/WAL/CPU限制"""
import os
import time
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("45.91.139.246", username="root",
          password=os.environ["PYSITE_SSH_PWD"], timeout=15)


def run(cmd, t=90):
    i, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode() + e.read().decode()[:300]


# 1) 等自动部署完成
print(run("sleep 70; tail -3 /www/wwwroot/pysite/scripts/k3s-deploy.log"))

# 2) 应用更新后的部署 yaml（去掉 CPU 限制）
print(run("export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; "
          "cd /www/wwwroot/pysite && kubectl apply -f k8s/deploy-nanjing.yaml "
          "-f k8s/deploy-hefei.yaml -f k8s/deploy-xuzhou.yaml "
          "-f k8s/deploy-wuxi.yaml -f k8s/deploy-hangzhou.yaml"))

# 3) 等滚动完成
print(run("export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; sleep 50; "
          "for s in nanjing hefei xuzhou wuxi hangzhou; do "
          "kubectl -n pysite rollout status deployment/pysite-$s --timeout=90s | tail -1; done", t=180))

# 4) 验证
print("== CPU limits ==")
print(run("export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; kubectl -n pysite get deploy "
          "-o custom-columns=N:.metadata.name,L:.spec.template.spec.containers[0].resources.limits"))
print("== gzip 首页 ==")
print(run("curl -s -o /dev/null -w 'size=%{size_download} enc=%header{content-encoding}\\n' "
          "-H 'Accept-Encoding: gzip' --max-time 10 http://127.0.0.1:8103/"))
print("== uploads 缓存头 ==")
print(run("f=$(ls /www/wwwroot/pysite/sites/xuzhou/uploads/ | head -1); "
          "curl -sD- -o /dev/null --max-time 8 http://127.0.0.1:8103/uploads/$f | grep -iE 'cache-control|etag|HTTP/'"))
print("== WAL ==")
print(run("ls /www/wwwroot/pysite/sites/xuzhou/storage/ | grep site.db; "
          "sqlite3 /www/wwwroot/pysite/sites/xuzhou/storage/site.db 'PRAGMA journal_mode;'"))
print("== 五站状态 ==")
print(run("for p in 8101 8102 8103 8104 8105; do echo -n \"$p:\"; "
          "curl -s -o /dev/null -w '%{http_code} ' --max-time 8 http://127.0.0.1:$p/; done; echo"))
print("== 内存 ==")
print(run("free -m | head -2"))
c.close()
