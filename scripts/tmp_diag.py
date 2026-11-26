# -*- coding: utf-8 -*-
"""临时诊断2：nginx gzip 配置与实际传输大小"""
import os
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("45.91.139.246", username="root",
          password=os.environ["PYSITE_SSH_PWD"], timeout=15)

cmds = [
    ("nginx gzip 配置", "grep -rn 'gzip' /www/server/nginx/conf/nginx.conf | head; "
     "ls /www/server/panel/vhost/nginx/ | head -20"),
    ("站点 vhost 示例", "f=$(ls /www/server/panel/vhost/nginx/*.conf | grep -iv dashboard | head -1); "
     "echo $f; cat $f"),
    ("首页实际传输大小(经nginx,带gzip)", "curl -s -o /dev/null -w 'size=%{size_download} gzip=%{header.gzip}\\n' "
     "--max-time 10 -H 'Accept-Encoding: gzip' http://127.0.0.1/ -H 'Host: ${HOST_未知名}' || true"),
    ("uploads 缓存头", "curl -sI --max-time 5 http://127.0.0.1:8103/uploads/nonexist.jpg | head -8"),
]
for name, cmd in cmds:
    print(f"===== {name} =====")
    i, o, e = c.exec_command(cmd, timeout=60)
    print(o.read().decode()[:2500])
c.close()
