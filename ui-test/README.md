# UI Test

เปิดหน้า UI ได้ที่ `http://localhost:8080`

หน้าจอนี้ใช้ backend ที่ `http://localhost:18080` เป็นตัวกลางสำหรับ:

- เช็กสถานะ Kong, Prometheus, Grafana, Ollama และฐานข้อมูล
- ยิง traffic ผ่าน Kong เพื่อสร้าง latency metrics
- ถาม chatbot ว่า route ไหนช้าที่สุดในช่วงล่าสุด

ถ้า Kong ตอบ `404` แปลว่ายังไม่ได้ apply ไฟล์ `kong/kong.yml` ไปที่ Konnect control plane
