import asyncio
import logging
import time
import multiprocessing
import httpx
import secrets
import mimetypes
import os
import requests
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from WebStreamer import Var, utils
from WebStreamer.bot import multi_clients, work_loads
import nest_asyncio

nest_asyncio.apply()

task_list = []
queue = multiprocessing.Queue(maxsize=15)
class_cache = {}


def calc_divisional_range(filesize, chuck=10):
    step = filesize // chuck
    arr = list(range(0, filesize, step))
    result = []
    for i in range(len(arr) - 1):
        s_pos, e_pos = arr[i], arr[i + 1] - 1
        result.append([s_pos, e_pos])
    result[-1][-1] = filesize - 1
    return result


# 线程下载方法
def range_download(url, save_name, s_pos, e_pos):
    headers = {"Range": f"bytes={s_pos}-{e_pos}"}
    res = requests.get(url, headers=headers, stream=True)
    chunk_list = []
    for chunk in res.iter_content(chunk_size=Var.DOWNLOAD_CACHE*(1024**2)):
        chunk_list.append(chunk)
    with open(save_name, "rb+") as f:
        f.seek(s_pos)
        for chunk in chunk_list:
            f.write(chunk)
    del chunk_list
    # with open(save_name, "rb+") as f:
    #     f.seek(s_pos)
    #     for chunk in res.iter_content(chunk_size=2*(1024**2)):
    #         if chunk:
    #             f.write(chunk)


def upload(file_name, cloud_path):
    status = True
    err = ''
    file_path = os.path.join(Var.DOWNLOAD_PATH, file_name)
    try:
        comm = f'rclone move "{file_path}" {cloud_path} --ignore-existing'
        os.system(comm)
    except Exception as e:
        err = e
        logging.debug(f'upload error: {e}')
        status = False
    finally:
        try:
            os.remove(os.path.join(file_path))
        except:
            pass
    return status, err


def download(m_id, file_name, file_size):
    status = 0
    err = ''
    if not os.path.exists(Var.DOWNLOAD_PATH):
        os.makedirs(Var.DOWNLOAD_PATH)
    save_path = os.path.join(Var.DOWNLOAD_PATH, file_name)
    if file_name in os.listdir(Var.DOWNLOAD_PATH):
        local_file_size = os.path.getsize(save_path)
        if local_file_size == file_size:
            status = 1
        else:
            status = 2
    else:
        try:
            divisional_ranges = calc_divisional_range(file_size, 10)
            with open(save_path, "wb") as f:
                pass
            with ThreadPoolExecutor() as p:
                futures = []
                for s_pos, e_pos in divisional_ranges:
                    futures.append(p.submit(media_streamer, m_id, save_path, s_pos, e_pos))
                as_completed(futures)

        except Exception as e:
            status = 3
            err = e
    return status, err


def send_msg(user_id, text):
    url = 'https://api.telegram.org/bot{}/sendMessage?chat_id={}&text={}'.format(Var.BOT_TOKEN, user_id, text)
    httpx.get(url)


def media_streamer(message_id, file_name, from_bytes, until_bytes):
    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]
    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logging.debug(f"Streamer: Using cached ByteStreamer object for client {index}")
    else:
        logging.debug(f"Streamer: Creating new ByteStreamer object for client {index}")
        tg_connect = utils.ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    logging.debug(f"Streamer: before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(message_id)
    logging.debug(f"Streamer: after calling get_file_properties")
    chunk_size = Var.DOWNLOAD_CACHE * (1024 ** 2)
    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1
    part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )
    p = open(body, 'rb')
    with open(os.path.join(Var.DOWNLOAD_PATH, file_name), "rb+") as f:
        f.seek(from_bytes)
        f.write(p.read())
    p.close()
    del p


def workers(queue, name):
    while True:
        try:
            task = queue.get()
            url = task['m_id']
            file_name = task['file_name']
            file_size = task['file_size']
            m = task['m']
            logging.info(f'{name} Downloading {file_name}')
            download_status, down_err = download(url, file_name, file_size)
            if download_status != 3:
                if download_status == 1 or download_status == 0:
                    if Var.UPLOAD:
                        cloud_path = f"{Var.CLOUD_DRIVE}:{Var.CLOUD_PATH}"
                        upload_status, up_err = upload(file_name, cloud_path)
                        if upload_status:
                            text = f'{file_name} \n\nDownload complete and upload to {Var.CLOUD_DRIVE}'
                        else:
                            text = f'{file_name} \n\nDownload complete and upload error: {up_err}'
                    else:
                        text = f'{file_name} \n\nDownload complete'
                else:
                    text = f'{file_name} \n\nalready in queue'
            else:
                text = f'{file_name} \n\nDownload error: {down_err}'
                queue.put(task)
            logging.info(name + text.replace('\n', ''))
            send_msg(m, text)
        except KeyboardInterrupt:
            break
        time.sleep(1)



def start():
    for i in range(Var.MAX_WORKERS):
        name = f"Worker {i}"
        worker = multiprocessing.Process(target=workers, args=(queue, name,), name=name)
        worker.start()
        print(f'Starting - {name}')
    print("All workers started")
    # worker = multiprocessing.Process(target=workers, args=(queue,))
    # worker.start()


if __name__ == "__main__":
    start = []

