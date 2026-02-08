# สร้าง Image
build:
	docker build -t my-web-app .

# รัน Container
run:
	docker run -d -p 80:80 my-web-app

# คำสั่งล้างเครื่อง
clean:
	@echo "🧹 Cleaning up port 80 and stopping old processes..."
	-sudo service apache2 stop
	-sudo service nginx stop
	-sudo pkill python
	-sudo pkill python3
	-sudo fuser -k 80/tcp
	-docker rm -f $$(docker ps -aq)
	@echo "✅ System is clean!"

# คำสั่ง Deploy (ล้างก่อน -> สร้างใหม่ -> รัน)
deploy: clean build run