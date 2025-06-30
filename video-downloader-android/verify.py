import uiautomator2 as u2

# Connect to the device
d = u2.connect()

json_str = "{\"userId\":1,\"id\":1,\"title\":\"sunt aut facere repellat provident occaecati excepturi optio reprehenderit\",\"body\":\"quia et suscipit\\nsuscipit recusandae consequuntur expedita et cum\\nreprehenderit molestiae ut ut quas totam\\nnostrum rerum est autem sunt rem eveniet architecto\"}"

# Check if any visible UI element contains this text
if d(text=json_str).exists:
    print("0")
else:
    print("1")