# Hiểu dự án qua một ví dụ

Ghi chú tôi viết để tự hiểu dự án bằng lời đơn giản. Bạn đọc thấy chỗ nào chưa đúng hay chưa rõ thì cứ nhận xét và hỏi lại tôi. Đặc tả chính xác nằm ở [protocol.md](protocol.md) (ghép đôi: mục 5; truyền file: mục 3, 4) và [architecture.md](architecture.md).

**Ví dụ có 2 máy A và máy B. Giả sử máy A muốn gửi 1 file video 10 GB cho máy B.**

## 1. Luồng ghép đôi

- **Lý do phải ghép đôi:**
  - Hai máy A và B không biết nhau.
  - Nếu không ghép đôi mà cứ thế gửi file thì máy lạ trong cùng Wi-Fi đều gửi bừa được, hoặc giả làm máy B để lấy trộm file của máy A.
  - → Vì vậy 2 máy A và B cần làm quen và ghi nhớ nhau.
- **Các bước ghép đôi:**
  - **Bước 0:** lần đầu chạy, mỗi máy tự tạo một cặp khóa: khóa công khai (in trong chứng chỉ) và khóa riêng.
    - Khóa riêng dùng để tạo chữ ký, chỉ nằm trong máy, không bao giờ gửi đi.
    - Khóa công khai chỉ kiểm tra được chữ ký, không tạo được; ai xem cũng được.
    - Đảm bảo: từ khóa công khai không thể chế ra khóa riêng.
  - **Bước 1:** máy A gọi máy B.
    - `Máy B: teleport listen` → máy B sẵn sàng nhận làm quen với 1 máy lạ.
    - `Máy A: teleport pair 192.168.1.5` → máy A gọi tới đúng địa chỉ của máy B.
    - Cuộc gọi được mã hóa, nghĩa là máy C chỉ nghe trộm thì không đọc được; máy C chen vào giữa thì bị lộ ở bước so mã (bước 4).
    - Sau đó 2 máy giới thiệu bản thân, **tự xưng tên và mã máy**, nhưng **chưa chứng minh được**.
    - Máy **A đưa ra yêu cầu ghép đôi kèm căn cước (chứng chỉ)** của mình. Máy **B kiểm tra** căn cước có đúng mẫu không, có khớp với mã máy A vừa tự xưng không.
  - **Bước 2:** mỗi máy góp 1 số ngẫu nhiên; máy B gửi số của mình theo kiểu "phong bì niêm phong".
    - **Mã 6 số được tính từ chứng chỉ của 2 máy + 2 số ngẫu nhiên này.**
    - Mỗi máy góp một số ngẫu nhiên để tạo mã 6 số, và không máy nào được chọn số sau khi đã thấy số của máy kia. Nhờ số ngẫu nhiên mới mỗi lần, kẻ thứ 3 không thể tính trước trong 1 triệu khả năng để tìm ra mã trùng.
    - Cách làm:
      - `Máy B: "Đây là phong bì của tôi"` → **gửi kết quả băm** SHA-256 của số 1309, giấu số thật.
      - `Máy A: gửi thẳng số 0912` (không bỏ vào phong bì; đường truyền vẫn được mã hóa).
      - `Máy B: hiện mã lên màn hình, rồi mới mở phong bì: "Số của tôi là 1309"` → **máy A băm số 1309 để kiểm tra** có khớp phong bì không.
    - → Nhờ vậy máy A không biết trước số của máy B, còn máy B không đổi được số sau khi đã gửi phong bì, nên không ai gian lận được.
  - **Bước 3:** ký tên chứng minh chứng chỉ là của mình.
    - **Máy A ký cùng lúc gửi số 0912** ở bước 2. Tờ giấy được ký có chứng chỉ của 2 máy, số của máy A và phong bì của máy B trong phiên này.
    - `Máy A: dùng khóa riêng ký, gửi chữ ký đi`
    - `Máy B: dùng khóa công khai (trong chứng chỉ của máy A) kiểm tra; đúng thì máy A đúng là chủ của chứng chỉ`
    - Kẻ thứ 3 có thể có bản chép chứng chỉ nhưng không có khóa riêng nên không ký được.
    - Đảm bảo: chữ ký cũ không dùng lại được ở phiên khác (mỗi phiên có phong bì mới).
  - **Bước 4:** người dùng ở hai máy tự so mã bằng mắt.
    - Mỗi máy tự tính mã 6 số từ những gì nó nhìn thấy (2 chứng chỉ + 2 số ngẫu nhiên).
      - `Máy A thấy:  CCCD máy A + CCCD máy B + số 0912 + số 1309  →  băm SHA-256  →  123456`
      - `Máy B thấy:  CCCD máy A + CCCD máy B + số 0912 + số 1309  →  băm SHA-256  →  123456`
    - **Nếu có kẻ thứ 3 là máy C đứng giữa thì:**
      - `Máy A thấy:  CCCD máy A + CCCD máy C + ...  →  băm SHA-256  →  123456`
      - `Máy B thấy:  CCCD máy C + CCCD máy B + ...  →  băm SHA-256  →  654321`
      - → mã không khớp, không ghép đôi.
    - 2 mã khớp thì bấm xác nhận ở cả 2 máy để hoàn tất ghép đôi.
  - **Bước 5:** ghi sổ máy quen.
    - Mỗi máy lưu chứng chỉ của máy kia vào file `trusted.json`. Lần sau kết nối, 2 máy tự kiểm tra căn cước của nhau mà không phải hỏi lại nữa.

## 2. Gửi file

File lớn được chia nhỏ ra gửi từng phần (khối), kiểm tra từng phần rồi ghép lại ở máy nhận.

- **Bước 1:** máy A hỏi máy B.
  - `Máy A: Mình gửi video 10 GB được không?`
  - `Máy B: hỏi người dùng có nhận hay không`
- **Bước 2:** gửi từng phần, kiểm tra từng phần.
  - `Máy A: chia file thành phần 1, phần 2, phần 3, ..., mỗi phần kèm mã băm`
  - `Máy B: phần nào đúng thì ghi vào thư mục tạm ẩn trên ổ đĩa, phần nào sai thì báo gửi lại`
- **Bước 3:** ghi sổ trong lúc nhận.
  - Ghi phần đó xuống ổ đĩa xong hẳn rồi mới ghi vào sổ (file `.state`) "đã có phần này". → Đang gửi bị ngắt, kể cả tắt máy, thì không phải gửi lại toàn bộ, chỉ gửi phần còn thiếu.
- **Bước 4:** kiểm tra lần cuối.
  - `Nhận đủ tất cả các phần` → `đọc lại và kiểm lại toàn bộ` → đúng → đổi về tên gốc (ví dụ `tung.mp4`).
  - Trong lúc nhận, file nằm trong thư mục tạm ẩn `.teleport/`, nên người dùng không thấy file dở dang.
  - Nếu đã có sẵn `tung.mp4` thì tự đặt tên `tung (1).mp4`, không bao giờ ghi đè file cũ.


## 3. Luồng bấm "Nhận" (máy B)
Ví dụ: máy A gửi `tung.mp4`, máy B hiện hộp hỏi "Nhận / Từ chối". Chuyện gì xảy ra từ lúc A gửi lời hỏi tới khi khối đầu tiên nằm trên ổ đĩa B?
- **Bước 1: lời hỏi tới B và được kiểm.**
  - Lời hỏi (`offer`) của A đi qua kiểm tra hình thức trong `core/messages.py`: số file, kích thước khối, tên file có đúng luật không.
  - Máy trạng thái trong `core/transfer.py` kiểm tiếp theo tình hình: đã có lượt này chưa, hàng chờ có đầy không, nội dung có bị đổi giữa chừng không.
  - Tên file được làm sạch (bỏ ký tự nguy hiểm) và đặt lại nếu trùng.
  - B kiểm ổ đĩa còn đủ chỗ không **trước** khi hỏi người dùng. Thiếu chỗ thì từ chối luôn, không làm phiền.
- **Bước 2: hiện hộp hỏi.** Tầng app báo lên giao diện. Giao diện ghi lời mời vào sổ `OfferBook` rồi hiện hộp hỏi.
- **Bước 3: người dùng bấm "Nhận".**
  - `OfferBook` chỉ cho quyết định đầu tiên đi tiếp, nên bấm đúp hay Esc ngay sau đó không gây rối.
  - Giao diện không tự chạm vào node mà nhờ `NodeHost.call`, chuyển việc sang thread của node.
- **Bước 4: quyết định đi xuống lõi.** `transfers.decide` ở tầng app gọi `decide` của máy trạng thái (core). Nếu lượt không còn ở trạng thái "đang hỏi" thì quyết định bị bỏ qua, nên quyết định đến muộn hay trùng không làm hỏng gì.
- **Bước 5: core ra lệnh, app thực hiện.**
  - Core chỉ trả về danh sách việc cần làm: tạo thư mục tạm, mở file `.part`.
  - Tầng app thực hiện bằng hàng đợi đĩa riêng của lượt này, từng việc một, qua `DiskExecutor`.
  - Thư mục tạm và `transfer.json` phải nằm bền trên đĩa rồi, B mới gửi `accept` cho A. Nhờ vậy A không bao giờ gửi dữ liệu mà B có thể quên sau khi khởi động lại.
- **Bước 6: A gửi từng khối, B kiểm từng khối.**
  - Mỗi khối B tự băm lại và so với mã băm A gửi kèm. Sai thì bỏ khối đó.
  - Core kiểm thêm thứ tự: khối nằm ngoài khoảng, trùng, hay nhảy cóc đều bị chặn.
- **Bước 7: ghi khối đầu tiên xuống ổ đĩa.**
  - Core ra lệnh ghi, app đưa vào hàng đợi đĩa, `PartFile.write_at` ghi đúng vị trí `số khối × 1 MiB` trong file `.part`.
  - Lần kiểm cuối ngay trước khi ghi: khối phải đủ độ dài và không được nằm sau chỗ trống chưa ghi.
- Sau đó: cứ 16 khối thì ghi sổ `.state` ("đã có các phần này"). Nhận đủ thì đọc lại, kiểm toàn bộ, rồi đổi tên về `tung.mp4` mà không ghi đè (xem mục 2).
- Dòng lệnh làm giống hệt, chỉ khác phần đầu: gõ `c` thay cho bấm nút, và đi thẳng tới `transfers.decide` ở bước 4.


## Tầng trust
Lần đầu ghép đôi: A và B chưa quen nhau
- A gửi yêu cầu cho B, 2 máy giới thiệu bản thân
- 2 máy tạo số ngẫu nhiên gửi cho máy còn lại, nhưng chỉ máy A (bên khởi xướng) kèm chữ ký riêng. Chứng chỉ không phải bí mật, ai cũng lấy được, nên A phải ký để chứng minh mình giữ khóa riêng của chứng chỉ đó. Chữ ký gắn với chứng chỉ 2 máy, số của A và phong bì của B trong phiên đó nên không dùng lại được ở phiên khác.
- Máy B không cần ký: kết nối được bọc TLS 1.3, và khi bắt tay B buộc phải dùng khóa riêng, nên A đã biết B giữ khóa thật. Còn A không gửi chứng chỉ trong bắt tay nên TLS chưa chứng minh gì về A, chỗ trống đó được lấp bằng chữ ký này. B kiểm chữ ký trước khi hiện mã 6 số.
- Nguyên tắc khi gửi là: máy B sẽ bọc trong 1 phong bì thư gửi cho A, sau đó A gửi số ngẫu nhiên được mã hoá cho B, B thấy mã của A sau đó đọc số trong phong bì, lúc này A sẽ băm số ra để kiểm tra. Nhờ vậy mà A và B không thể biết trước và thay đổi số được
- Sau đó 2 máy sẽ tạo mã 6 số từ chứng chỉ và số ngẫu nhiên. Kẻ thứ 3 chỉ có 1/1000000 khả năng để trùng mã nên đảm bảo an toàn.
- Sau đó thông tin ghép đôi sẽ được lưu trong file trusted.json: mã máy, tên, fingerprint, chứng chỉ và thời gian kết nối
Lần sau khi đã ghép đôi: A muốn kết nối với B đã quen
- A kiểm tra chứng chỉ của B có trong trusted.json không
- Và B phải chứng minh được mình giữ khóa riêng của chứng chỉ đó ngay trong lúc bắt tay TLS. Lần này cả 2 chiều đều kiểm (mTLS): B cũng kiểm chứng chỉ của A có trong trusted.json, nên không cần ký thêm chữ ký ghép đôi nữa.

## Tầng net
- Tầng net đóng vai trò là đường đi an toàn để các máy tìm thấy nhau và truyền dữ liệu trong mạng
### 1. Cách để 2 máy A và B thấy nhau
- Để máy A và B thấy nhau mà không cần nhập IP, tầng net dùng giao thức mDNS. Mỗi máy sẽ tự động phát sóng trong mạng để thông báo sự hiện diện.
- Nếu bị chặn mDNS thì vẫn có thể nhập IP để kết nối.
### 2. Đường truyền bảo mật
- Sau khi máy A có được địa chỉ máy B, thì sẽ thiết lập kết nối TCP trực tiếp giữa 2 máy
- Đường truyền được bọc lớp mã hoá TLS 1.3 bảo mật cho mọi dữ liệu
- Dữ liệu được truyền thẳng từ ổ đĩa máy A sang máy B
### 3. Đọc ghi dữ liệu
- Chỉ nhận các gói byte từ core nhét vào socket và đọc các byte từ socket trả lời ngược lại, chỉ quản lý phần mở đóng kết nối mạng không can thiệp phần dữ liệu.

## Tầng core
Tầng core là bộ não logic của ứng dụng, luật ghép đôi, truyền file, kết nối lại. Theo thiết kế sans-IO
- Chỉ nhận đầu vào và tính toán đưa quyết định cho tầng khác làm
- Chịu trách nhiệm kiểm duyệt đảm bảo an toàn tuyệt đối
- Xử lý phần chia khối và đảm bảo toàn vẹn của dữ liệu: chia các file lớn thành các khối có kích thước 1mib, theo dõi tiến độ, xử lý thuật toán băm
- Độc lập với giao diện không phụ thuộc tầng nào cả.


## Tầng app
Tầng app đóng vai trò là quản lý của toàn bộ hệ thống là người thực thi tất cả các quyết định.
- Tầng app kết nối các tầng lại với nhau: lấy quyết định từ core bảo tầng net truyền dữ liệu đi và nhờ tầng trust kiểm tra bảo mật. Tầng giao diện người dùng ui/cli chỉ được nói chuyện với app
- Chịu trách nhiệm đọc/ghi ổ đĩa: tầng app đọc từng khối của file ở máy gửi và ghi từng khối nhận được xuống ổ đĩa ở máy nhận.
- Tầng app quản lý thư mục và lưu trữ thư mục ẩn, đảm bảo dữ liệu an toàn không bị mất, không làm hỏng dữ liệu, không ghi đè làm mất dữ liệu.


## Tầng ui / cli
Đây là hai "mặt tiền" của ứng dụng: ui là cửa sổ đồ họa (Qt), cli là dòng lệnh. Cả hai chỉ lo hiển thị và hỏi người dùng, không tự quyết gì về bảo mật hay truyền file.
- Cả hai chỉ nói chuyện với tầng app. Ví dụ bấm "Nhận" trên giao diện hay gõ `c` trên dòng lệnh đều cuối cùng gọi `transfers.decide` của app; từ đó trở xuống là cùng một đường.
- Câu chữ hiển thị nằm ở ui/cli. Tầng app chỉ trả mã kết quả, nên đổi ngôn ngữ không đụng vào logic.
### ui (giao diện Qt)
- Giao diện chạy ở thread chính, còn node chạy ở một thread riêng. Giao diện không được chạm vào node trực tiếp mà đi qua `NodeHost` (`ui/bridge.py`): gọi xuống bằng `host.call`, node báo ngược lên bằng signal. Làm vậy để hai thread không dùng chung dữ liệu.
- `OfferBook` (`ui/offer.py`) bảo đảm mỗi lời mời nhận file chỉ được trả lời đúng một lần, kể cả khi bấm hai nơi cùng lúc.
- `gcguard.py` giữ cho việc dọn rác của Python chỉ chạy ở thread giao diện, tránh crash do Qt bị hủy đối tượng sai thread.
### cli (dòng lệnh)
- Các lệnh `identity`, `list`, `pair`, `listen`, `send`, `receive` chỉ gọi app và in kết quả.
- Đọc bàn phím bằng thread nền với `os.read`, không dùng `input()` vì có thể gây lỗi khi tắt chương trình.
- Ctrl+C hai nấc: lần một dừng có trật tự, lần hai dừng cứng.
