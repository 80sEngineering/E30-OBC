import ujson as json
import logging
def access_data(data_type, data_to_write = None):
    try:
        with open('data.json', 'r') as file:
            data = json.load(file)
            result = data[data_type]
            file.close()
    except:
        logging.error(f"> Data {data_type} not found")
        return False

    if not data_to_write:
        return result
    else:
        with open('data.json', 'w') as file:
            data[data_type] = data_to_write
            json.dump(data, file)
            file.close()
        
