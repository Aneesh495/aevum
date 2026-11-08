.PHONY: doctor
doctor:
	python3.13 -c 'import platform, shutil; print(platform.platform()); print(shutil.disk_usage("."))'
