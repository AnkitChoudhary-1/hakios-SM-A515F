with open('/opt/a51-hakios/apps/Payload/Instagram.app/Instagram', 'rb') as f:
    data = f.read()
import re
target = b'<IGRegistrationStepControllerProtocol>'
idx = data.find(target)
surr = data[idx-200:idx+600]
print(re.sub(rb'[^\x20-\x7e\n]', rb'.', surr).decode('latin1'))
