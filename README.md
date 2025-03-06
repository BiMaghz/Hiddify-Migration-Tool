
# Hiddify Migration Toolkit  

This tool helps you migrate users from **Hiddify** to **Marzneshin**.
It also generates `.htaccess` rules for subscription URLs.  

## How to Use  

1. **Clone the repository:**  
   ```bash
   git clone https://github.com/Bimaghz/Hiddify-Migration-Tool.git
   cd Hiddify-Migration-Tool
   ```

2. **Set up environment variables:**  
   ```bash
   cp .env.example .env && nano .env
   ```

3. **Install dependencies:**  
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the tool:**  
   ```bash
   python3 main.py
   ```

5. Upload .htaccess file into **public_html**. Choose one of sub templates below and use **public_html/sub** for it :
- [Template 1](https://github.com/MatinDehghanian/Ourenus)
- [Template 2](https://github.com/MatinDehghanian/MarzneshinTemplate1)
